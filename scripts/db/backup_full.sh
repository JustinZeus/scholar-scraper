#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/../.." && pwd)"

usage() {
  cat <<'USAGE'
Usage: scripts/db/backup_full.sh [--plain]

Creates a PostgreSQL logical backup from the running `db` compose service.

Options:
  --plain    Write a plain SQL dump instead of custom-format dump.
  -h, --help Show this help.

Environment:
  BACKUP_DIR         Destination directory (default: <repo>/backups)
  BACKUP_PREFIX      File prefix (default: scholarr)
  USE_DEV_COMPOSE    Set to 1 to include docker-compose.dev.yml
USAGE
}

format="custom"
while (($#)); do
  case "$1" in
    --plain)
      format="plain"
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

compose_cmd=(docker compose -f "${project_root}/docker-compose.yml")
if [[ "${USE_DEV_COMPOSE:-0}" == "1" && -f "${project_root}/docker-compose.dev.yml" ]]; then
  compose_cmd+=(-f "${project_root}/docker-compose.dev.yml")
fi

backup_dir="${BACKUP_DIR:-${project_root}/backups}"
backup_prefix="${BACKUP_PREFIX:-scholarr}"
mkdir -p "${backup_dir}"

timestamp="$(date -u +"%Y%m%dT%H%M%SZ")"
if [[ "${format}" == "plain" ]]; then
  backup_file="${backup_dir}/${backup_prefix}_${timestamp}.sql"
  dump_cmd='pg_dump --no-owner --no-acl -U "$POSTGRES_USER" "$POSTGRES_DB"'
else
  backup_file="${backup_dir}/${backup_prefix}_${timestamp}.dump"
  dump_cmd='pg_dump --format=custom --no-owner --no-acl -U "$POSTGRES_USER" "$POSTGRES_DB"'
fi

"${compose_cmd[@]}" exec -T db sh -lc "${dump_cmd}" > "${backup_file}"

echo "Backup created: ${backup_file}"
