# Contributing

## Scope
This project favors small, reviewable pull requests that keep runtime behavior clear and operationally safe.

## Essential-File Policy
Commit only source-of-truth files required to build, run, test, or document the app.

Do not commit generated or local-only artifacts, including:
- `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`
- frontend build/install outputs like `frontend/dist/`, `frontend/node_modules/`, `frontend/.vite/`
- coverage outputs (`.coverage`, `htmlcov/`)
- packaging/build leftovers (`*.egg-info/`, `build/`, `dist/`)
- local probe/scratch material (`planning/`)

CI enforces this with `scripts/check_no_generated_artifacts.sh`.

## Merge Checklist
- [ ] Changes are minimal, purposeful, and remove obsolete/dead code in touched areas.
- [ ] Backend tests pass (`uv run pytest tests/unit` and integration scope as needed).
- [ ] Frontend checks pass (`npm run typecheck`, `npm run test:run`, `npm run build`).
- [ ] API/behavior docs are updated when env vars, endpoints, or payloads change.
- [ ] `README.md`, `.env.example`, and deployment notes stay aligned.
- [ ] `scripts/check_no_generated_artifacts.sh` passes locally.
