"""Найти запущенные docker compose-проекты для подсказок в UI."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from app.compose_ops import ensure_under_projects_root, normalize_project_path, path_as_file_uri
from app.config import PROJECTS_HOST_ROOT
from app.registry import Project, detect_compose_file

PANEL_SELF_DIR_BASENAME = "local-dev-panel"


def _norm(p: str) -> str:
    return normalize_project_path(p)


def _split_config_files(config_files: str) -> list[str]:
    out: list[str] = []
    if not config_files or not config_files.strip():
        return out
    for chunk in config_files.split(","):
        c = chunk.strip()
        if c:
            out.append(c)
    return out


def _status_running(status: str | None) -> bool:
    if not status:
        return False
    s = status.strip().lower()
    return "running" in s


def _suggest_domain(compose_project_name: str, taken: set[str]) -> str:
    raw = (compose_project_name or "").strip().lower()
    raw = raw.replace("_", "-")
    raw = re.sub(r"[^a-z0-9.-]", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-").strip(".")
    if not raw:
        raw = "stack"
    base = raw
    cand = f"{base}.loc"
    n = 2
    while cand in taken:
        cand = f"{base}-{n}.loc"
        n += 1
    return cand


def _is_panel_self(workdir: str) -> bool:
    return Path(_norm(workdir)).name == PANEL_SELF_DIR_BASENAME


def _root_ok(workdir: str) -> bool:
    if not PROJECTS_HOST_ROOT:
        return False
    try:
        ensure_under_projects_root(workdir)
    except ValueError:
        return False
    return True


def _from_compose_ls() -> tuple[list[dict] | None, str | None]:
    """Либо список сырых dict из `docker compose ls`, либо None при ошибке CLI."""
    proc = subprocess.run(
        ["docker", "compose", "ls", "-a", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if proc.returncode != 0:
        hint = proc.stderr.strip() or proc.stdout.strip()
        return None, hint or f"exit {proc.returncode}"
    raw = proc.stdout.strip()
    if not raw:
        return [], None
    rows: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not rows:
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                rows = [x for x in arr if isinstance(x, dict)]
        except json.JSONDecodeError:
            return None, "не удалось распарсить вывод compose ls"
    return rows, None


def _row_from_ls_item(item: dict) -> dict | None:
    name = item.get("Name") or ""
    status = item.get("Status") or ""
    cfg = item.get("ConfigFiles") or ""
    if not name or not _status_running(status):
        return None
    paths = _split_config_files(cfg)
    if not paths:
        return None
    first = _norm(paths[0])
    workdir = str(Path(first).parent)
    compose_file = Path(first).name
    return {
        "compose_project": name,
        "working_dir": workdir,
        "compose_file": compose_file,
        "status": status,
    }


def _from_running_containers() -> list[dict]:
    """Fallback: метки com.docker.compose.* на запущенных контейнерах."""
    pq = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if pq.returncode != 0:
        return []
    out_map: dict[tuple[str, str], dict] = {}
    for cid in pq.stdout.split():
        cid = cid.strip()
        if not cid:
            continue
        ir = subprocess.run(
            ["docker", "inspect", cid, "-f", "{{json .Config.Labels}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if ir.returncode != 0:
            continue
        try:
            labels = json.loads(ir.stdout)
        except json.JSONDecodeError:
            continue
        if not isinstance(labels, dict):
            continue
        proj = (labels.get("com.docker.compose.project") or "").strip()
        if not proj:
            continue
        wd_label = (labels.get("com.docker.compose.project.working_dir") or "").strip()
        cfg_label = labels.get("com.docker.compose.project.config_files") or ""
        paths = _split_config_files(str(cfg_label))
        if paths:
            first = _norm(paths[0])
            workdir = str(Path(first).parent)
            compose_file = Path(first).name
        elif wd_label:
            workdir = _norm(wd_label)
            found = detect_compose_file(workdir)
            if not found:
                continue
            compose_file = found
        else:
            continue
        key = (workdir, compose_file)
        if key not in out_map:
            out_map[key] = {
                "compose_project": proj,
                "working_dir": workdir,
                "compose_file": compose_file,
                "status": "running",
            }
    return list(out_map.values())


def discover_running_not_in_registry(
    registered: list[Project],
) -> tuple[list[dict], str | None]:
    """
    Возвращает проекты с запущенным compose, которых ещё нет в реестре (по каталогу).
    Каждый элемент: compose_project, working_dir, compose_file, suggested_domain,
    root_ok, skip_reason (если не предлагаем кнопку).
    """
    reg_paths = {_norm(p.host_path) for p in registered}
    taken_domains = {p.domain.lower() for p in registered}

    raw_rows, ls_err = _from_compose_ls()
    candidates: list[dict] = []
    used_fallback = False
    if raw_rows is not None:
        for item in raw_rows:
            if not isinstance(item, dict):
                continue
            row = _row_from_ls_item(item)
            if row:
                candidates.append(row)
    if not candidates:
        used_fallback = True
        candidates = _from_running_containers()

    hint: str | None = None
    if ls_err:
        hint = f"compose ls недоступен ({ls_err})."
        if used_fallback:
            hint += " Использован обход через метки запущенных контейнеров."

    seen: set[tuple[str, str]] = set()
    suggestions: list[dict] = []
    for row in candidates:
        wd = _norm(row["working_dir"])
        cf = row["compose_file"]
        key = (wd, cf)
        if key in seen:
            continue
        seen.add(key)
        if wd in reg_paths:
            continue
        if _is_panel_self(wd):
            continue
        proj = row["compose_project"]
        root = _root_ok(wd)
        skip_reason: str | None = None
        if not root:
            skip_reason = (
                f"каталог вне PROJECTS_HOST_ROOT ({PROJECTS_HOST_ROOT}) "
                "— расширьте bind в compose панели или поменяйте корень в .env"
            )
        dom = _suggest_domain(proj, taken_domains)
        taken_domains.add(dom)
        suggestions.append(
            {
                "compose_project": proj,
                "working_dir": wd,
                "compose_file": cf,
                "suggested_domain": dom,
                "root_ok": root,
                "skip_reason": skip_reason,
                "status": row.get("status", "running"),
                "folder_uri": path_as_file_uri(wd),
            }
        )

    return suggestions, hint
