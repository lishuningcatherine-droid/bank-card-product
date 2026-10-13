# Ingestion worker: bankrec pipeline + Playwright Chromium + supercronic (cron for containers). Non-root.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
ARG SUPERCRONIC_VERSION=v0.2.33
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates postgresql-client \
    && curl -fsSL -o /usr/local/bin/supercronic \
       "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && chmod +x /usr/local/bin/supercronic && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini ./
COPY docker/worker-entrypoint.sh /usr/local/bin/worker-entrypoint.sh
RUN uv sync --frozen --no-dev && mkdir -p /app/data /app/reports && chown -R pwuser /app/data /app/reports
ENV PATH="/app/.venv/bin:$PATH" BANKREC_ENV=prod BANKREC_SCHEDULER=worker CAPTURE_RUNNER_LABEL=worker \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
USER pwuser
ENTRYPOINT ["/usr/local/bin/worker-entrypoint.sh"]
