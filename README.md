# docker-ui-cp-local

Локальная **веб-панель** для переключения между проектами на **Docker Compose**: меньше ручного `cd`, `docker compose up -d` и `docker compose down` в терминале — запуск и остановка стеков из браузера, с подсказкой по уже запущенным compose и правкой куска `/etc/hosts`.

**Репозиторий:** [github.com/iravenss/docker-ui-cp-local](https://github.com/iravenss/docker-ui-cp-local)

---

## Зачем это

Если вы **задолбались** каждый раз набирать одни и те же команды, чтобы переключиться с одного локального стека (Bitrix, Laravel, WordPress…) на другой — эта панель держит **реестр проектов** (путь, compose-файл, домен, ссылка в браузер) и дергает `docker compose` за вас. Обычный сценарий: **одновременно поднят один «тяжёлый» стек** на те же порты (например `:80`), остальные остановлены; тома при `down` **не удаляются** (без `-v`).

---

## Важно про происхождение кода

Проект в значительной степени собран как **вайбкод** (с помощью ИИ-ассистента): это **личная утилита**, а не промышленный продукт. Перед использованием на своей машине прочитайте раздел про безопасность и ограничения.

---

## На чём проверялось

Сейчас панель **осознанно тестировалась только на Linux Ubuntu** с Docker Engine и Compose v2. На других дистрибутивах, macOS или Windows с Docker Desktop поведение может отличаться (пути, сокет, `file://` для «открыть папку»).

---

## Куда заходить после установки

1. Поднимите контейнер панели (см. ниже).
2. Откройте в браузере на **той же машине**, где крутится Docker:

   **`http://127.0.0.1:7580`**

   При желании добавьте в `/etc/hosts` имя вроде `mycp.loc` и открывайте `http://mycp.loc:7580` — порт **7580** обязателен, если не поднимаете отдельный прокси на `:80`.

---

## Требования

- **Docker** с **Compose v2** (`docker compose` в PATH на хосте).
- Каталог со всеми проектами, который вы готовы **смонтировать в контейнер тем же абсолютным путём**, что и на хосте (см. `compose.yaml` и `PROJECTS_HOST_ROOT`).

---

## Установка и запуск

```bash
git clone https://github.com/iravenss/docker-ui-cp-local.git
cd docker-ui-cp-local

cp .env.example .env
# Отредактируйте .env: задайте PROJECTS_HOST_ROOT — общий родитель каталогов ваших проектов, например /home/you/dev

docker compose up -d --build
```

Дальше откройте **`http://127.0.0.1:7580`**.

### Первые шаги в интерфейсе

1. В блоке **«Локальные домены»** при необходимости добавьте `mycp.loc` (или оставьте только IP-URL выше).
2. В **«Проекты»** добавьте записи (домен для hosts, каталог с `docker-compose.yml` / `compose.yaml`, опционально ссылка `http`/`https` с портом).
3. **Запуск / стоп** — отдельное окно с **потоковым логом** `docker compose` (SSE); при успешном завершении окно закроется и страница обновится.
4. Режим **solo**: перед `up` у выбранного проекта остальные приложения из реестра получают `compose down` (без `-v`).

### Правка `/etc/hosts` с хоста

Панель управляет только маркированным блоком между строками:

`# <<< local-dev-panel begin >>>` … `# <<< local-dev-panel end >>>`

**Вариант A** — монтирование `/etc/hosts` и root в контейнере (только для своей машины, осознайте риски):

```bash
docker compose -f compose.yaml -f compose.hosts.example.yaml up -d --build
```

См. [`compose.hosts.example.yaml`](compose.hosts.example.yaml).

**Вариант B** — не монтировать hosts: интерфейс покажет текст блока для ручной вставки, если записать файл из контейнера нельзя.

Подробнее про переменные — в [`.env.example`](.env.example).

---

## Данные панели

Каталог `./data` (volume в compose, в `.gitignore`):

| Файл | Назначение |
|------|------------|
| `projects.yaml` | Реестр проектов |
| `extra_domains.yaml` | Доп. имена только для hosts |
| `state.yaml` | Последний успешно запущенный проект (подсказка в UI) |

---

## Разработка без Docker (опционально)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export PROJECTS_HOST_ROOT=/abs/path/to/projects
export DATA_DIR="$(pwd)/data"
mkdir -p "$DATA_DIR"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

На хосте нужны `docker` и `docker compose`.

---

## Безопасность

- Контейнер монтирует **`/var/run/docker.sock`**: по смыслу это почти как доступ пользователя с правами Docker на хосте. **Не выставляйте** порт панели в интернет без защиты (TLS, VPN, firewall).
- Правка `/etc/hosts` из контейнера — только осознанно и на своей машине.

---

## Публикация в GitHub (для мейнтейнера)

Репозиторий: **https://github.com/iravenss/docker-ui-cp-local**

```bash
git init
git add .
git commit -m "Initial import: local Docker Compose control panel"
git branch -M main
git remote add origin https://github.com/iravenss/docker-ui-cp-local.git
git push -u origin main
```

Если репозиторий уже создан на GitHub пустым, первого пуша достаточно. Для аутентификации используйте **Personal Access Token** (HTTPS) или SSH-ключ (`git@github.com:iravenss/docker-ui-cp-local.git`).

---

## Лицензия

Код распространяется «как есть», без гарантий. При необходимости добавьте свою лицензию в репозиторий.
