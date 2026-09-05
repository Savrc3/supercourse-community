FROM python:3.10-slim

WORKDIR /app
COPY server/pyproject.toml server/uv.lock ./server/
RUN pip install --no-cache-dir uv \
    && uv sync --project server --frozen --no-dev
COPY server/app ./server/app
COPY server/alembic ./server/alembic
COPY server/alembic.ini ./server/alembic.ini

WORKDIR /app/server
EXPOSE 8090
CMD ["sh", "-c", "uv run --frozen alembic upgrade head && uv run --frozen uvicorn app.main:app --host ${SC_HOST:-0.0.0.0} --port ${SC_PORT:-8090}"]
