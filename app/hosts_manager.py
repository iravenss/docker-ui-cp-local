"""Manage marker block inside /etc/hosts."""

from __future__ import annotations

MARKER_BEGIN = "# <<< local-dev-panel begin >>>"
MARKER_END = "# <<< local-dev-panel end >>>"

IP_LINE = "127.0.0.1"


def parse_managed_hostnames(content: str) -> set[str]:
    """Parse hostnames from our block (one per line after IP)."""
    lines = content.splitlines()
    out: set[str] = set()
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped == MARKER_BEGIN:
            in_block = True
            continue
        if stripped == MARKER_END:
            break
        if not in_block:
            continue
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) >= 2 and parts[0] == IP_LINE:
            for host in parts[1:]:
                if host.startswith("#"):
                    break
                out.add(host.lower())
    return out


def remove_managed_block(content: str) -> tuple[str, set[str]]:
    """Return content without our block and hostnames that were inside."""
    lines = content.splitlines()
    out_lines: list[str] = []
    in_block = False
    found = False
    stored: set[str] = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == MARKER_BEGIN:
            found = True
            in_block = True
            i += 1
            continue
        if in_block and stripped == MARKER_END:
            in_block = False
            i += 1
            continue
        if in_block:
            parts = stripped.split()
            if len(parts) >= 2 and parts[0] == IP_LINE:
                for host in parts[1:]:
                    if not host.startswith("#"):
                        stored.add(host.lower())
            i += 1
            continue
        out_lines.append(line)
        i += 1
    body = "\n".join(out_lines)
    if body and not body.endswith("\n"):
        body += "\n"
    if found and stored:
        pass
    return body, stored


def build_managed_block(hostnames: set[str]) -> str:
    names = sorted({h.lower().strip() for h in hostnames if h.strip()})
    inner = "\n".join(f"{IP_LINE} {name}" for name in names)
    if not inner:
        return f"{MARKER_BEGIN}\n{MARKER_END}\n"
    return f"{MARKER_BEGIN}\n{inner}\n{MARKER_END}\n"


def inject_block(content: str, hostnames: set[str]) -> str:
    without, _ = remove_managed_block(content)
    block = build_managed_block(hostnames)
    if not without.endswith("\n") and without:
        without += "\n"
    if without and not without.endswith("\n\n"):
        return without.rstrip("\n") + "\n\n" + block
    return without + block
