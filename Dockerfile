# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first (cacheable layer) — postgres extra is required
# because compose runs against the postgres service; s3 stays opt-in.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra postgres

# Install the project itself.
COPY gateway ./gateway
COPY alembic ./alembic
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra postgres


FROM python:3.12-slim AS runtime

WORKDIR /app

# Bring over the venv + source.
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

# Run migrations against whatever DB the env points at, then serve. Single-
# replica deployment assumption — multi-replica needs a separate migrate job.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn gateway.api:app --host 0.0.0.0 --port 8080"]
