#!/usr/bin/env sh
set -eu

uv run python /app/scripts/wait_for_db.py

if [ "${MIGRATE_ON_START:-1}" = "1" ]; then
  uv run alembic upgrade head
fi

if [ "${BOOTSTRAP_ADMIN_ON_START:-0}" = "1" ]; then
  uv run python /app/scripts/bootstrap_admin.py
fi

if [ "$#" -eq 0 ]; then
  if [ "${APP_RELOAD:-0}" = "1" ]; then
    set -- uv run uvicorn app.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}" --reload
  else
    set -- uv run uvicorn app.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}" --workers "${UVICORN_WORKERS:-1}"
  fi
fi

exec "$@"
