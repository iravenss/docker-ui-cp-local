"""Read/write /etc/hosts block; merge with desired hostnames from app data."""

from __future__ import annotations

from pathlib import Path

from app.hosts_manager import (
    build_managed_block,
    inject_block,
    parse_managed_hostnames,
    remove_managed_block,
)


def read_hosts_raw(hosts_path: Path) -> str | None:
    try:
        return hosts_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def write_hosts_block(hosts_path: Path, hostnames: set[str]) -> tuple[bool, str]:
    """
    Rewrite only the managed block. Returns (ok, message).
    If not ok, message is human-readable hint or block to paste.
    """
    current = read_hosts_raw(hosts_path)
    if current is None:
        try:
            hosts_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        current = ""
    new_content = inject_block(current, hostnames)
    try:
        hosts_path.write_text(new_content, encoding="utf-8")
        return True, "Файл hosts обновлён."
    except OSError as e:
        block = build_managed_block(hostnames)
        hint = (
            f"Не удалось записать {hosts_path}: {e}\n\n"
            "Вставьте вручную в конец файла /etc/hosts следующий блок "
            "(или выполните от root):\n\n"
            f"{block}"
        )
        return False, hint


def hostnames_in_file(hosts_path: Path) -> set[str]:
    raw = read_hosts_raw(hosts_path)
    if raw is None:
        return set()
    return parse_managed_hostnames(raw)
