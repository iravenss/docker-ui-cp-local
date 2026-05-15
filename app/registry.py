"""Serialize / deserialize project registry and extra domain list."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import yaml
from pydantic import BaseModel, Field, field_validator

from app.config import DATA_DIR, EXTRA_DOMAINS_FILE, PROJECTS_FILE

_HOSTNAME_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


def validate_hostname(name: str) -> str:
    name = name.strip().lower()
    if not name or len(name) > 253 or not _HOSTNAME_RE.match(name):
        raise ValueError("Некорректное имя хоста")
    return name


def normalize_public_url(raw: str | None) -> str | None:
    """
    Проверка и нормализация полного URL сайта (http/https, порт, путь).
    Пустая строка → None.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if "://" not in s:
        s = "http://" + s
    parsed = urlparse(s)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError("Ссылка должна начинаться с http:// или https://")
    host = parsed.hostname
    if host is None:
        raise ValueError("В адресе нужен хост, например https://site.loc:8443/")
    normalized = urlunparse(
        (
            scheme,
            parsed.netloc,
            parsed.path or "",
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )
    return normalized


def effective_public_url(p: "Project") -> str:
    """Абсолютный URL для href; при ошибке в public_url — запасной http://domain/."""
    if p.public_url:
        s = p.public_url.strip()
        if s:
            try:
                n = normalize_public_url(s)
                if n:
                    return n
            except ValueError:
                pass
    return f"http://{p.domain}/"


def browser_link_label(p: "Project") -> str:
    """Текст ссылки: валидный public_url как ввели/нормализовано, иначе запасной URL."""
    if p.public_url and p.public_url.strip():
        raw = p.public_url.strip()
        try:
            normalized = normalize_public_url(raw)
            return normalized or raw
        except ValueError:
            pass
    return effective_public_url(p).rstrip("/") or f"http://{p.domain}"


class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    domain: str
    host_path: str
    display_name: str | None = None
    description: str | None = None
    public_url: str | None = None
    compose_file: str | None = None
    add_to_hosts: bool = True
    type: str = "application"

    @field_validator("display_name")
    @classmethod
    def _display_name_strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None

    @field_validator("description")
    @classmethod
    def _description_strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        return s[:4000]

    @field_validator("public_url")
    @classmethod
    def _public_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        return normalize_public_url(s)

    @field_validator("domain")
    @classmethod
    def _domain(cls, v: str) -> str:
        return validate_hostname(v)

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in ("application", "infra"):
            raise ValueError("type must be application or infra")
        return v


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_projects() -> list[Project]:
    _ensure_data_dir()
    if not PROJECTS_FILE.is_file():
        return []
    raw = yaml.safe_load(PROJECTS_FILE.read_text(encoding="utf-8"))
    if not raw:
        return []
    items = raw if isinstance(raw, list) else raw.get("projects", [])
    out: list[Project] = []
    for row in items:
        if isinstance(row, dict):
            out.append(Project.model_validate(row))
    return out


def save_projects(projects: list[Project]) -> None:
    _ensure_data_dir()
    data = [p.model_dump(mode="python") for p in projects]
    PROJECTS_FILE.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def load_extra_domains() -> list[str]:
    _ensure_data_dir()
    if not EXTRA_DOMAINS_FILE.is_file():
        return []
    raw = yaml.safe_load(EXTRA_DOMAINS_FILE.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [validate_hostname(str(x)) for x in raw if str(x).strip()]
    return []


def save_extra_domains(domains: list[str]) -> None:
    _ensure_data_dir()
    EXTRA_DOMAINS_FILE.write_text(
        yaml.safe_dump(domains, allow_unicode=True),
        encoding="utf-8",
    )


def detect_compose_file(project_dir: str) -> str | None:
    base = Path(project_dir)
    for name in ("compose.yaml", "docker-compose.yml", "docker-compose.yaml"):
        if (base / name).is_file():
            return name
    return None
