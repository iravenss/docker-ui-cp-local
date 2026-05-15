"""Потоковый запуск docker compose (stdout+stderr в одном потоке)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


def compose_cmd(project_dir: str, compose_filename: str, *args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-directory",
        project_dir,
        "-f",
        compose_filename,
        *args,
    ]


async def stream_compose(
    project_dir: str,
    compose_filename: str,
    *compose_args: str,
) -> AsyncIterator[dict]:
    """
    Асинхронно запускает compose и отдаёт события:
    - {"t": "line", "text": "..."} — строка вывода
    - {"t": "exit", "code": int} — код завершения
    """
    cmd = compose_cmd(project_dir, compose_filename, *compose_args)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=project_dir,
    )
    if proc.stdout is None:
        rc = await proc.wait()
        yield {"t": "exit", "code": rc}
        return
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").rstrip("\r\n")
        yield {"t": "line", "text": text}
    rc = await proc.wait()
    yield {"t": "exit", "code": rc}
