# TRACE API.
# Build context is the repository root so the ClickHouse schema ships with the image:
#   docker build -f backend/Dockerfile .
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/trace

# Dependencies first so application edits do not invalidate the layer.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
COPY deploy/clickhouse /srv/trace/deploy/clickhouse

# Evidence is streamed through a spool directory owned by the service account.
RUN useradd --system --uid 10001 --create-home trace \
    && mkdir -p /srv/trace/data \
    && chown -R trace:trace /srv/trace
USER trace

ENV TRACE_CLICKHOUSE_SCHEMA_DIR=/srv/trace/deploy/clickhouse \
    TRACE_DATABASE_URL=sqlite+aiosqlite:////srv/trace/data/trace.db

EXPOSE 8000

# No curl in the image; the probe uses the interpreter that is already here.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
