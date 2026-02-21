#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/../.." && pwd)"

usage() {
  cat <<'USAGE'
Usage: scripts/db/restore_dump.sh --file <path> [--wipe-public]

Restores a PostgreSQL dump into the running `db` compose service.

Options:
  --file <path>   Required. Backup file (.dump custom format or .sql plain).
  --wipe-public   Drop and recreate public schema before restore.
  -h, --help      Show this help.

Environment:
  USE_DEV_COMPOSE   Set to 1 to include docker-compose.dev.yml
USAGE
}

dump_file=""
wipe_public="0"
while (($#)); do
  case "$1" in
    --file)
      dump_file="${2:-}"
      shift 2
      ;;
    --wipe-public)
      wipe_public="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${dump_file}" ]]; then
  echo "--file is required" >&2
  usage >&2
  exit 2
fi
if [[ ! -f "${dump_file}" ]]; then
  echo "Dump file not found: ${dump_file}" >&2
  exit 2
fi

compose_cmd=(docker compose -f "${project_root}/docker-compose.yml")
if [[ "${USE_DEV_COMPOSE:-0}" == "1" && -f "${project_root}/docker-compose.dev.yml" ]]; then
  compose_cmd+=(-f "${project_root}/docker-compose.dev.yml")
fi

if [[ "${wipe_public}" == "1" ]]; then
  "${compose_cmd[@]}" exec -T db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
fi

case "${dump_file}" in
  *.dump)
    cat "${dump_file}" | "${compose_cmd[@]}" exec -T db sh -lc 'pg_restore --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB" -'
    ;;
  *.sql)
    cat "${dump_file}" | "${compose_cmd[@]}" exec -T db sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB"'
    ;;
  *)
    echo "Unsupported file extension. Expected .dump or .sql" >&2
    exit 2
    ;;
esac

echo "Restore completed: ${dump_file}"
