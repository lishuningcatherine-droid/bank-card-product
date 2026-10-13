# API image: FastAPI + bankrec CLI (migrations, seed). Runs as a non-root user.
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev && useradd --system --uid 10001 --home /app bankrec && mkdir -p /app/data /app/reports \
    && chown -R bankrec /app/data /app/reports
ENV PATH="/app/.venv/bin:$PATH" BANKREC_ENV=prod
USER bankrec
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health').status==200 else 1)"
CMD ["uvicorn", "bankrec.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header", "--proxy-headers"]
