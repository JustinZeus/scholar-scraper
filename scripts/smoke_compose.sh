#!/usr/bin/env bash
set -euo pipefail

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-scholarr-smoke}"
export APP_PORT="${APP_PORT:-8000}"
export APP_HOST_PORT="${APP_HOST_PORT:-18000}"
export POSTGRES_PORT="${POSTGRES_PORT:-15432}"

cleanup() {
  docker compose down -v --remove-orphans
}

trap cleanup EXIT

docker compose up -d --build

echo "Waiting for application health check..."
for _ in {1..45}; do
  if curl -fsS "http://localhost:${APP_HOST_PORT}/healthz" >/dev/null; then
    break
  fi
  sleep 2
done

curl -fsS "http://localhost:${APP_HOST_PORT}/healthz" >/dev/null

docker compose run --rm app uv run pytest tests/smoke -m "integration and smoke"
