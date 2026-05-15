"""Path guards and subprocess helpers for docker compose."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.config import PROJECTS_HOST_ROOT


def normalize_project_path(raw: str) -> str:
    return os.path.normpath(os.path.expanduser(raw.strip()))


def path_as_file_uri(abs_path: str) -> str:
    """URI file:///... для ссылки «открыть папку» в браузере на рабочей станции."""
    try:
        return Path(abs_path).expanduser().resolve(strict=False).as_uri()
    except ValueError:
        p = Path(abs_path).expanduser()
        if not p.is_absolute():
            return ""
        try:
            return p.as_uri()
        except ValueError:
            return ""


def ensure_under_projects_root(abs_path: str) -> Path:
    if not PROJECTS_HOST_ROOT:
        raise ValueError("PROJECTS_HOST_ROOT не задан")
    resolved = normalize_project_path(abs_path)
    root = normalize_project_path(PROJECTS_HOST_ROOT)
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ValueError(
            "Путь должен находиться внутри PROJECTS_HOST_ROOT "
            f"({PROJECTS_HOST_ROOT})"
        )
    return Path(resolved)


def run_compose(project_dir: str, compose_filename: str, *args: str) -> subprocess.CompletedProcess[str]:
    cmd: list[str] = [
        "docker",
        "compose",
        "--project-directory",
        project_dir,
        "-f",
        compose_filename,
        *args,
    ]
    return subprocess.run(
        cmd,
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def format_proc(proc: subprocess.CompletedProcess[str]) -> str:
    out = ""
    if proc.stdout:
        out += proc.stdout
    if proc.stderr:
        if out:
            out += "\n"
        out += proc.stderr
    if proc.returncode != 0:
        out += f"\n[exit {proc.returncode}]"
    return out.strip()
