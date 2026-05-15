"""Store long dashboard messages outside query strings."""

from __future__ import annotations

import uuid

from app.config import DATA_DIR

FLASH_DIR = DATA_DIR / "_flash"


def stash(message: str) -> str:
    FLASH_DIR.mkdir(parents=True, exist_ok=True)
    fid = str(uuid.uuid4())
    path = FLASH_DIR / f"{fid}.txt"
    path.write_text(message, encoding="utf-8")
    return fid


def pop(token: str) -> str | None:
    path = FLASH_DIR / f"{token}.txt"
    if not path.is_file():
        return None
    try:
        txt = path.read_text(encoding="utf-8")
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    return txt
