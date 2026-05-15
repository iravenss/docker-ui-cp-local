"""Application configuration from environment."""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
PROJECTS_FILE = DATA_DIR / "projects.yaml"
EXTRA_DOMAINS_FILE = DATA_DIR / "extra_domains.yaml"
STATE_FILE = DATA_DIR / "state.yaml"
PROJECTS_HOST_ROOT = os.environ.get("PROJECTS_HOST_ROOT", "").rstrip("/")
HOSTS_PATH = Path(os.environ.get("HOSTS_PATH", "/etc/hosts"))
SOLO_MODE_DEFAULT = os.environ.get("SOLO_MODE_DEFAULT", "true").lower() in (
    "1",
    "true",
    "yes",
)
