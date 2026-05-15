FROM python:3.12-slim-bookworm

ARG COMPOSE_VERSION=2.32.4

RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       ca-certificates \
       curl \
       docker.io \
  && ARCH="$(dpkg --print-architecture)" \
  && case "$ARCH" in \
       amd64) DARCH="x86_64" ;; \
       arm64) DARCH="aarch64" ;; \
       *) echo "unsupported arch $ARCH"; exit 1 ;; \
     esac \
  && mkdir -p /usr/local/lib/docker/cli-plugins \
  && curl -fsSL \
       "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-${DARCH}" \
       -o /usr/local/lib/docker/cli-plugins/docker-compose \
  && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/

ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
