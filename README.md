# scholarr

<div align="center">

Self-hosted scholar tracking with a single app image (API + frontend).

[![CI](https://img.shields.io/github/actions/workflow/status/justinzeus/scholarr/ci.yml?style=for-the-badge)](https://github.com/JustinZeus/scholar-scraper/actions/workflows/ci.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/justinzeus/scholarr?style=for-the-badge&logo=docker)](https://hub.docker.com/r/justinzeus/scholarr)
[![Docker Image](https://img.shields.io/badge/docker-justinzeus%2Fscholarr-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://hub.docker.com/r/justinzeus/scholarr)

</div>

## Quick Start

1. Copy env template:

```bash
cp .env.example .env
```

2. Set required values in `.env`:
- `POSTGRES_PASSWORD`
- `SESSION_SECRET_KEY`

3. Start stack:

```bash
docker compose pull
docker compose up -d
```

Open:
- App/API: `http://localhost:8000`
- Health: `http://localhost:8000/healthz`

## Documentation

Primary docs live under `docs/`.

- Index: `docs/README.md`
- Deploy and dev workflow: `docs/deploy/quickstart.md`
- Environment reference: `docs/reference/environment.md`
- API contract and payload conventions: `docs/reference/api_contract.md`
- Architecture and domain boundaries: `docs/architecture/domain_boundaries.md`
- Scrape safety runbook: `docs/ops/scrape_safety_runbook.md`
- DB backup/restore/integrity runbook: `docs/ops/db_runbook.md`
- Migration rollout checklist: `docs/ops/migration_checklist.md`
- Frontend theme inventory: `docs/frontend/theme_phase0_inventory.md`
- Contributing policy: `docs/contributing.md`

## Docs Site (Docusaurus)

Docusaurus source lives in `website/` and consumes markdown from `docs/`.

Local build:

```bash
cd website
npm install
npm run build
```

GitHub Pages deploy is automated via `.github/workflows/docs-pages.yml`.

## Quality Gates

Backend:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app uv run pytest tests/unit
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app uv run pytest -m integration
```

Frontend:

```bash
cd frontend
npm install
npm run typecheck
npm run test:run
npm run build
```

Contract and env checks:

```bash
python3 scripts/check_frontend_api_contract.py
python3 scripts/check_env_contract.py
./scripts/check_no_generated_artifacts.sh
```
