#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROUTER_DIR = ROOT / "app" / "api" / "routers"
FRONTEND_API_DIRS = [
    ROOT / "frontend" / "src" / "features",
    ROOT / "frontend" / "src" / "lib" / "auth",
    ROOT / "frontend" / "src" / "lib" / "api",
]

BACKEND_PREFIX = "/api/v1"
BACKEND_ROUTE_PREFIX_RE = re.compile(r'router\s*=\s*APIRouter\(\s*prefix\s*=\s*"([^"]+)"')
BACKEND_DECORATOR_RE = re.compile(r'@router\.(get|post|put|patch|delete)\(\s*"([^"]*)"')

FRONTEND_CALL_RE = re.compile(
    r'apiRequest(?:<[\s\S]*?>)?\(\s*("[^"]+"|\'[^\']+\'|`[^`]+`)\s*,\s*(\{[\s\S]{0,280}?\})',
    re.MULTILINE,
)
FRONTEND_METHOD_RE = re.compile(r'method\s*:\s*"([A-Z]+)"')


def normalize_path(path: str) -> str:
    cleaned = path.strip()
    if not cleaned:
        return "/"

    if "?" in cleaned:
        cleaned = cleaned.split("?", 1)[0]

    cleaned = re.sub(r"\$\{[^}]+\}", "{}", cleaned)
    cleaned = re.sub(r"\{[^}]+\}", "{}", cleaned)

    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"

    if len(cleaned) > 1 and cleaned.endswith("/"):
        cleaned = cleaned.rstrip("/")

    return cleaned


def read_backend_routes() -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()

    for path in sorted(BACKEND_ROUTER_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")

        prefix_match = BACKEND_ROUTE_PREFIX_RE.search(text)
        if not prefix_match:
            continue

        router_prefix = prefix_match.group(1)

        for method, route_path in BACKEND_DECORATOR_RE.findall(text):
            if route_path:
                full_path = f"{BACKEND_PREFIX}{router_prefix}{route_path}"
            else:
                full_path = f"{BACKEND_PREFIX}{router_prefix}"

            routes.add((method.upper(), normalize_path(full_path)))

    return routes


def read_frontend_routes() -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()

    files: list[Path] = []
    for directory in FRONTEND_API_DIRS:
        if directory.exists():
            files.extend(sorted(directory.rglob("*.ts")))

    for path in files:
        text = path.read_text(encoding="utf-8")

        for path_literal, options_block in FRONTEND_CALL_RE.findall(text):
            raw_path = path_literal.strip("`\"'")
            if not raw_path.startswith("/"):
                continue

            method_match = FRONTEND_METHOD_RE.search(options_block)
            method = method_match.group(1) if method_match else "GET"
            normalized = normalize_path(f"{BACKEND_PREFIX}{raw_path}")
            routes.add((method, normalized))

    return routes


def main() -> int:
    backend_routes = read_backend_routes()
    frontend_routes = read_frontend_routes()

    missing = sorted(frontend_routes - backend_routes)

    if missing:
        print("Frontend API contract drift detected. Missing backend routes:")
        for method, route in missing:
            print(f"- {method} {route}")
        return 1

    print(
        f"Frontend API contract check passed: {len(frontend_routes)} frontend routes match backend definitions."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
