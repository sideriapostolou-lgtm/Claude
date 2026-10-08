# nightcrawler - Railway image (owner: O6). Build only; deploy when the owner says go.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    PORT=8080

WORKDIR /app

# Non-root user that owns the data volume mount point.
RUN useradd --create-home --uid 10001 bot \
    && mkdir -p /data \
    && chown bot:bot /data

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[live,judge]"

USER bot
EXPOSE 8080
CMD ["nightcrawler", "run"]
