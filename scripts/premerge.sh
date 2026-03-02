#!/usr/bin/env bash
set -euo pipefail

DC="docker compose -f docker-compose.yml -f docker-compose.dev.yml"

passed=0
failed=0
failures=()

step() {
  local label="$1"
  shift
  printf '\n\033[1;34m── %s\033[0m\n' "$label"
  if "$@"; then
    printf '\033[1;32m   PASS\033[0m  %s\n' "$label"
    ((passed++)) || true
  else
    printf '\033[1;31m   FAIL\033[0m  %s\n' "$label"
    ((failed++)) || true
    failures+=("$label")
  fi
}

# ── repo hygiene (host-side, no runtime deps) ────────────────────────────────
step "No generated artifacts"        ./scripts/check_no_generated_artifacts.sh
step "Env contract parity"           python3 scripts/check_env_contract.py
step "API contract drift"            python3 scripts/check_frontend_api_contract.py

# ── backend lint + typecheck ─────────────────────────────────────────────────
step "Ruff check"                    $DC run --rm app ruff check .
step "Ruff format"                   $DC run --rm app ruff format --check .
step "Mypy"                          $DC run --rm app mypy app/ --ignore-missing-imports

# ── backend tests ────────────────────────────────────────────────────────────
step "Unit tests"                    $DC run --rm app python -m pytest tests/unit
step "Integration tests"             $DC run --rm app python -m pytest -m integration

# ── frontend ─────────────────────────────────────────────────────────────────
step "Frontend theme tokens"         $DC run --rm frontend npm run check:theme-tokens
step "Frontend typecheck"            $DC run --rm frontend npm run typecheck
step "Frontend unit tests"           $DC run --rm frontend npm run test:run
step "Frontend build"                $DC run --rm frontend npm run build

# ── docs ─────────────────────────────────────────────────────────────────────
step "Docs build"                    npm --prefix docs/website run build

# ── summary ──────────────────────────────────────────────────────────────────
printf '\n\033[1;34m── Summary ─────────────────────────────────────────────\033[0m\n'
printf '   %s passed, %s failed\n' "$passed" "$failed"
if ((failed > 0)); then
  printf '\n\033[1;31m   Failed steps:\033[0m\n'
  for f in "${failures[@]}"; do
    printf '     - %s\n' "$f"
  done
  exit 1
else
  printf '\n\033[1;32m   All checks passed.\033[0m\n'
fi
