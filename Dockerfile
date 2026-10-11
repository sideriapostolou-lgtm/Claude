# nightcrawler - Railway image (owner: O6). Build only; deploy when the owner says go.
#
#   docker build -t nightcrawler .
#   docker run --rm -p 8080:8080 -v nightcrawler-data:/data --env-file .env nightcrawler
#
# Runs as the non-root user "bot" (uid 10001); the installed code is owned by
# root and read-only to it. All state (SQLite ledger, KILL file, datasets) lives
# in DATA_DIR=/data, which must be a persistent volume.
# Railway mounts volumes as root, so on Railway set the service variable
# RAILWAY_RUN_UID=0 (Railway's documented fix for non-root images with a volume).
# Docker Hub rate-limits Railway's shared builders (429 on 2026-10-09); AWS's public mirror of the same official image
# (public.ecr.aws/docker/library) serves it without a pull limit.
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    PORT=8080

WORKDIR /app

RUN useradd --create-home --uid 10001 --user-group bot \
    && mkdir -p /data \
    && chown bot:bot /data

COPY pyproject.toml README.md ./
COPY src ./src
# Smoke-test the install: the console script must import with every optional extra present.
RUN pip install ".[live,judge]" \
    && python -c "import nightcrawler.cli, solders, anthropic"

USER bot
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8080') + '/healthz', timeout=4)"
CMD ["nightcrawler", "run"]
