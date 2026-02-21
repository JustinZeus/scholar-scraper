# Deploy and Dev Quickstart

## Required Setup

1. Copy `.env.example` to `.env`.
2. Set `POSTGRES_PASSWORD`.
3. Set `SESSION_SECRET_KEY`.

## Deploy Method A: Prebuilt Image

```bash
docker compose pull
docker compose up -d
```

Open:
- App/API: `http://localhost:8000`
- Health endpoint: `http://localhost:8000/healthz`

Upgrade:

```bash
docker compose pull
docker compose up -d
```

## Deploy Method B: Local Source + Dev Frontend

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Open:
- API: `http://localhost:8000`
- Frontend dev server: `http://localhost:5173`

Stop:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

## Quality Commands

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

Repository checks:

```bash
python3 scripts/check_frontend_api_contract.py
python3 scripts/check_env_contract.py
./scripts/check_no_generated_artifacts.sh
```
