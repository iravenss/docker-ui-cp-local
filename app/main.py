"""FastAPI control panel."""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import yaml
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.compose_discover import discover_running_not_in_registry
from app.compose_ops import (
    ensure_under_projects_root,
    format_proc,
    normalize_project_path,
    path_as_file_uri,
    run_compose,
)
from app.compose_stream import stream_compose
from app.flash_store import pop as flash_pop
from app.flash_store import stash as flash_stash
from app.config import DATA_DIR, HOSTS_PATH, PROJECTS_HOST_ROOT, SOLO_MODE_DEFAULT, STATE_FILE
from app.hosts_io import hostnames_in_file, write_hosts_block
from app.registry import (
    Project,
    browser_link_label,
    detect_compose_file,
    effective_public_url,
    load_extra_domains,
    load_projects,
    normalize_public_url,
    save_extra_domains,
    save_projects,
    validate_hostname,
)

app = FastAPI(title="local-dev-panel")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _write_state(last_id: str | None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        yaml.safe_dump({"last_started_id": last_id}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _read_state() -> str | None:
    if not STATE_FILE.is_file():
        return None
    data = yaml.safe_load(STATE_FILE.read_text(encoding="utf-8")) or {}
    return data.get("last_started_id")


def _desired_hostnames() -> set[str]:
    names = set(load_extra_domains())
    for p in load_projects():
        if p.add_to_hosts and p.type == "application":
            names.add(p.domain)
    return names


def _apply_hosts() -> tuple[bool, str]:
    return write_hosts_block(HOSTS_PATH, _desired_hostnames())


MAX_QUERY_LEN = 800


def _redirect(notice: str | None = None, error: str | None = None) -> RedirectResponse:
    """Редирект; длинные тексты сохраняем в data/_flash как fn=.&fn=.&"""
    parts: list[str] = []
    if notice:
        if len(notice.encode("utf-8")) <= MAX_QUERY_LEN:
            parts.append(f"notice={urllib.parse.quote(notice)}")
        else:
            parts.append(f"fn={flash_stash(notice)}")
    if error:
        if len(error.encode("utf-8")) <= MAX_QUERY_LEN:
            parts.append(f"error={urllib.parse.quote(error)}")
        else:
            parts.append(f"fe={flash_stash(error)}")
    url = "/?" + "&".join(parts) if parts else "/"
    return RedirectResponse(url, status_code=303)


def _compose_file_for(p: Project) -> tuple[str | None, str | None]:
    if p.compose_file:
        return p.compose_file, None
    found = detect_compose_file(p.host_path)
    if not found:
        return None, "Не найден compose.yaml / docker-compose.yml в каталоге проекта"
    return found, None


def _project_up(p: Project) -> bool:
    cf, err = _compose_file_for(p)
    if err or not cf:
        return False
    proc = run_compose(p.host_path, cf, "ps", "-q")
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _sse(obj: dict) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")


async def _stream_start_body(project_id: str, solo: str):
    solo_on = solo == "1"
    projects = load_projects()
    target = next((p for p in projects if p.id == project_id), None)
    if not target:
        yield _sse({"t": "error", "message": "Проект не найден."})
        yield _sse({"t": "done", "ok": False})
        return
    if target.type != "application":
        yield _sse({"t": "error", "message": "Тип infra не запускается как приложение."})
        yield _sse({"t": "done", "ok": False})
        return
    try:
        ensure_under_projects_root(target.host_path)
    except ValueError as e:
        yield _sse({"t": "error", "message": str(e)})
        yield _sse({"t": "done", "ok": False})
        return
    cf, err = _compose_file_for(target)
    if err or not cf:
        yield _sse({"t": "error", "message": err or "Нет compose-файла."})
        yield _sse({"t": "done", "ok": False})
        return

    if solo_on:
        for p in projects:
            if p.id == project_id or p.type != "application":
                continue
            pcf, perr = _compose_file_for(p)
            if perr or not pcf:
                continue
            yield _sse({"t": "phase", "title": f"solo: docker compose down — {p.domain}"})
            async for ev in stream_compose(p.host_path, pcf, "down"):
                yield _sse(ev)

    yield _sse({"t": "phase", "title": f"docker compose up -d — {target.domain}"})
    up_ok = False
    async for ev in stream_compose(target.host_path, cf, "up", "-d"):
        yield _sse(ev)
        if ev.get("t") == "exit":
            up_ok = ev.get("code") == 0
    if up_ok:
        _write_state(target.id)
    yield _sse({"t": "done", "ok": up_ok})


async def _stream_stop_body(project_id: str):
    projects = load_projects()
    target = next((p for p in projects if p.id == project_id), None)
    if not target:
        yield _sse({"t": "error", "message": "Проект не найден."})
        yield _sse({"t": "done", "ok": False})
        return
    cf, err = _compose_file_for(target)
    if err or not cf:
        yield _sse({"t": "error", "message": err or "Нет compose-файла."})
        yield _sse({"t": "done", "ok": False})
        return
    yield _sse({"t": "phase", "title": f"docker compose down — {target.domain}"})
    down_ok = False
    async for ev in stream_compose(target.host_path, cf, "down"):
        yield _sse(ev)
        if ev.get("t") == "exit":
            down_ok = ev.get("code") == 0
    if _read_state() == project_id:
        _write_state(None)
    yield _sse({"t": "done", "ok": down_ok})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    flash_notice = ""
    flash_error = ""
    if fn := request.query_params.get("fn"):
        flash_notice = flash_pop(fn) or ""
    if fe := request.query_params.get("fe"):
        flash_error = flash_pop(fe) or ""
    notice = flash_notice or (request.query_params.get("notice") or "")
    err = flash_error or (request.query_params.get("error") or "")
    projects = load_projects()
    extras = load_extra_domains()
    desired = _desired_hostnames()
    in_file = hostnames_in_file(HOSTS_PATH)
    last_id = _read_state()
    rows: list[dict] = []
    for p in projects:
        cf, cerr = _compose_file_for(p)
        up = _project_up(p) if cf and not cerr else False
        rows.append(
            {
                "p": p,
                "compose_file": cf,
                "compose_error": cerr,
                "running": up,
                "last_started": p.id == last_id,
                "folder_uri": path_as_file_uri(p.host_path),
                "browser_href": effective_public_url(p),
                "browser_label": browser_link_label(p),
            }
        )
    docker_suggestions, discover_hint = discover_running_not_in_registry(projects)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "projects": rows,
            "docker_suggestions": docker_suggestions,
            "discover_hint": discover_hint,
            "extra_domains": extras,
            "desired_hostnames": sorted(desired),
            "hosts_file_hostnames": sorted(in_file),
            "hosts_path": str(HOSTS_PATH),
            "projects_root": PROJECTS_HOST_ROOT or "(не задан)",
            "solo_default": SOLO_MODE_DEFAULT,
            "notice": notice,
            "error": err,
        },
    )


@app.post("/extra-domains/add")
async def extra_add(domain: str = Form(...)) -> RedirectResponse:
    try:
        name = validate_hostname(domain)
    except ValueError as e:
        return _redirect(error=str(e))
    cur = load_extra_domains()
    if name not in cur:
        cur.append(name)
        save_extra_domains(cur)
    ok, msg = _apply_hosts()
    if not ok:
        return _redirect(notice=msg)
    return _redirect(notice=f"Домен {name} добавлен в hosts.")


@app.post("/extra-domains/remove")
async def extra_remove(domain: str = Form(...)) -> RedirectResponse:
    name = domain.strip().lower()
    cur = [d for d in load_extra_domains() if d != name]
    save_extra_domains(cur)
    ok, msg = _apply_hosts()
    if not ok:
        return _redirect(notice=msg)
    return _redirect(notice=f"Домен {name} убран из списка и блока hosts.")


@app.post("/hosts/apply")
async def hosts_apply() -> RedirectResponse:
    ok, msg = _apply_hosts()
    if ok:
        return _redirect(notice=msg)
    return _redirect(error=msg)


@app.post("/projects/add")
async def project_add(
    domain: str = Form(...),
    host_path: str = Form(...),
    display_name: str = Form(""),
    description: str = Form(""),
    public_url: str = Form(""),
    compose_file: str = Form(""),
    add_to_hosts: str | None = Form(None),
) -> RedirectResponse:
    pub_raw = (public_url or "").strip() or None
    try:
        pub = normalize_public_url(pub_raw) if pub_raw else None
    except ValueError as e:
        return _redirect(error=str(e))
    try:
        path = str(ensure_under_projects_root(host_path))
        p = Project(
            domain=domain,
            host_path=path,
            display_name=display_name.strip() or None,
            description=description.strip() or None,
            public_url=pub,
            add_to_hosts=add_to_hosts == "on",
        )
        cf = (compose_file or "").strip()
        if cf:
            p.compose_file = cf
        else:
            found = detect_compose_file(path)
            if not found:
                return _redirect(
                    error="В каталоге нет compose.yaml / docker-compose.yml — укажите файл вручную."
                )
            p.compose_file = found
    except ValidationError as e:
        err_obj = e.errors()[0] if e.errors() else {}
        msg = err_obj.get("msg") or err_obj.get("type") or str(e)
        ctx = err_obj.get("ctx", {})
        if isinstance(ctx, dict) and "error" in ctx:
            msg = str(ctx["error"])
        return _redirect(error=str(msg))
    except ValueError as e:
        return _redirect(error=str(e))
    cur = load_projects()
    for x in cur:
        if x.domain == p.domain:
            return _redirect(error=f"Проект с доменом (hosts) {p.domain} уже есть.")
        if normalize_project_path(x.host_path) == normalize_project_path(p.host_path):
            return _redirect(
                error=f"Каталог уже есть в реестре (домен {x.domain})."
            )
    cur.append(p)
    save_projects(cur)
    ok, msg = _apply_hosts()
    if not ok:
        return _redirect(notice=f"Проект сохранён. {msg}")
    return _redirect(notice="Проект добавлен; hosts синхронизированы.")


@app.post("/projects/{project_id}/update")
async def project_update(
    project_id: str,
    domain: str = Form(...),
    host_path: str = Form(...),
    display_name: str = Form(""),
    description: str = Form(""),
    public_url: str = Form(""),
    compose_file: str = Form(""),
    add_to_hosts: str | None = Form(None),
) -> RedirectResponse:
    cur = load_projects()
    idx = next((i for i, pp in enumerate(cur) if pp.id == project_id), None)
    if idx is None:
        return _redirect(error="Проект не найден.")
    old = cur[idx]

    pub_raw = (public_url or "").strip() or None
    try:
        pub = normalize_public_url(pub_raw) if pub_raw else None
    except ValueError as e:
        return _redirect(error=str(e))
    try:
        dom = validate_hostname(domain)
        path = str(ensure_under_projects_root(host_path))
    except ValueError as e:
        return _redirect(error=str(e))

    cf_strip = (compose_file or "").strip()
    if cf_strip:
        compose_name = cf_strip
    else:
        compose_name = detect_compose_file(path)
        if not compose_name:
            return _redirect(
                error="В каталоге нет compose.yaml / docker-compose.yml — укажите файл вручную."
            )

    for i, x in enumerate(cur):
        if i == idx:
            continue
        if x.domain == dom:
            return _redirect(error=f"Проект с доменом (hosts) {dom} уже есть.")
        if normalize_project_path(x.host_path) == normalize_project_path(path):
            return _redirect(error=f"Каталог уже занят записью ({x.domain}).")

    try:
        updated = old.model_copy(
            update={
                "domain": dom,
                "host_path": path,
                "display_name": display_name.strip() or None,
                "description": description.strip() or None,
                "public_url": pub,
                "compose_file": compose_name,
                "add_to_hosts": add_to_hosts == "on",
            }
        )
    except ValidationError as e:
        err_obj = e.errors()[0] if e.errors() else {}
        msg = err_obj.get("msg") or str(e)
        ctx = err_obj.get("ctx", {})
        if isinstance(ctx, dict) and "error" in ctx:
            msg = str(ctx["error"])
        return _redirect(error=str(msg))

    cur[idx] = updated
    save_projects(cur)
    ok, msg = _apply_hosts()
    if not ok:
        return _redirect(notice=f"Сохранено. {msg}")
    return _redirect(notice="Проект обновлён.")


@app.post("/projects/{project_id}/delete")
async def project_delete(project_id: str) -> RedirectResponse:
    cur = [p for p in load_projects() if p.id != project_id]
    save_projects(cur)
    if _read_state() == project_id:
        _write_state(None)
    ok, msg = _apply_hosts()
    if not ok:
        return _redirect(notice=f"Проект удалён. {msg}")
    return _redirect(notice="Проект удалён из реестра.")


@app.post("/projects/{project_id}/stream/start")
async def project_start_stream(
    project_id: str,
    solo: str = Form("1"),
) -> StreamingResponse:
    return StreamingResponse(
        _stream_start_body(project_id, solo),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/projects/{project_id}/stream/stop")
async def project_stop_stream(project_id: str) -> StreamingResponse:
    return StreamingResponse(
        _stream_stop_body(project_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/projects/{project_id}/start")
async def project_start(
    project_id: str,
    solo: str = Form("1"),
) -> RedirectResponse:
    solo_on = solo == "1"
    projects = load_projects()
    target = next((p for p in projects if p.id == project_id), None)
    if not target:
        return _redirect(error="Проект не найден.")
    if target.type != "application":
        return _redirect(error="Тип infra не запускается как приложение.")
    try:
        ensure_under_projects_root(target.host_path)
    except ValueError as e:
        return _redirect(error=str(e))
    cf, err = _compose_file_for(target)
    if err or not cf:
        return _redirect(error=err or "Нет compose-файла.")
    messages: list[str] = []
    if solo_on:
        for p in projects:
            if p.id == project_id or p.type != "application":
                continue
            pcf, perr = _compose_file_for(p)
            if perr or not pcf:
                continue
            down = run_compose(p.host_path, pcf, "down")
            messages.append(f"{p.domain}: docker compose down → {format_proc(down)}")
    up = run_compose(target.host_path, cf, "up", "-d")
    if up.returncode != 0:
        return _redirect(error=f"Ошибка запуска {target.domain}:\n{format_proc(up)}")
    _write_state(target.id)
    tail = "\n".join(messages[-3:]) if messages else ""
    note = f"Запущен {target.domain}.\n{tail}".strip()
    return _redirect(notice=note)


@app.post("/projects/{project_id}/stop")
async def project_stop(project_id: str) -> RedirectResponse:
    projects = load_projects()
    target = next((p for p in projects if p.id == project_id), None)
    if not target:
        return _redirect(error="Проект не найден.")
    cf, err = _compose_file_for(target)
    if err or not cf:
        return _redirect(error=err or "Нет compose-файла.")
    down = run_compose(target.host_path, cf, "down")
    if _read_state() == project_id:
        _write_state(None)
    if down.returncode != 0:
        return _redirect(error=f"{target.domain}:\n{format_proc(down)}")
    return _redirect(notice=f"Остановлен {target.domain}.\n{format_proc(down)}")


@app.post("/stop-all-applications")
async def stop_all() -> RedirectResponse:
    projects = load_projects()
    parts: list[str] = []
    for p in projects:
        if p.type != "application":
            continue
        cf, err = _compose_file_for(p)
        if err or not cf:
            parts.append(f"{p.domain}: пропуск ({err or 'нет compose'})")
            continue
        down = run_compose(p.host_path, cf, "down")
        parts.append(f"{p.domain}:\n{format_proc(down)}")
    _write_state(None)
    return _redirect(notice="\n\n".join(parts))
