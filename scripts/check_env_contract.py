#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "app" / "settings.py"
ENV_EXAMPLE_PATH = ROOT / ".env.example"

SETTINGS_ENV_HELPERS = {"_env_bool", "_env_int", "_env_float", "_env_str"}
ALLOWED_ENV_EXAMPLE_EXTRAS = {
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "TEST_DATABASE_URL",
    "SCHOLARR_IMAGE",
    "APP_HOST",
    "APP_PORT",
    "APP_HOST_PORT",
    "APP_RELOAD",
    "FRONTEND_HOST_PORT",
    "CHOKIDAR_USEPOLLING",
    "VITE_DEV_API_PROXY_TARGET",
    "MIGRATE_ON_START",
    "BOOTSTRAP_ADMIN_ON_START",
    "BOOTSTRAP_ADMIN_EMAIL",
    "BOOTSTRAP_ADMIN_PASSWORD",
    "BOOTSTRAP_ADMIN_FORCE_PASSWORD",
    "DB_WAIT_TIMEOUT_SECONDS",
    "DB_WAIT_INTERVAL_SECONDS",
}


def _call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return None


def _first_str_arg(node: ast.Call) -> str | None:
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _settings_env_names() -> set[str]:
    tree = ast.parse(SETTINGS_PATH.read_text(encoding="utf-8"))
    names: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node)
        if call_name is None:
            continue
        if call_name != "os.getenv" and call_name not in SETTINGS_ENV_HELPERS:
            continue
        env_name = _first_str_arg(node)
        if not env_name:
            continue
        names.add(env_name)
    return names


def _env_example_names() -> tuple[set[str], set[str]]:
    names: set[str] = set()
    duplicates: set[str] = set()

    for raw_line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if not key:
            continue
        if key in names:
            duplicates.add(key)
        names.add(key)
    return names, duplicates


def main() -> int:
    settings_names = _settings_env_names()
    env_names, duplicate_names = _env_example_names()

    missing = sorted(settings_names - env_names)
    unknown = sorted(env_names - settings_names - ALLOWED_ENV_EXAMPLE_EXTRAS)
    duplicates = sorted(duplicate_names)

    if missing or unknown or duplicates:
        print("Environment contract check failed.")
        if missing:
            print("Missing from .env.example (referenced in app/settings.py):")
            for name in missing:
                print(f"- {name}")
        if unknown:
            print("Unknown keys in .env.example (not in app/settings.py or allowlist):")
            for name in unknown:
                print(f"- {name}")
        if duplicates:
            print("Duplicate keys in .env.example:")
            for name in duplicates:
                print(f"- {name}")
        return 1

    print(
        "Environment contract check passed: "
        f"{len(settings_names)} settings keys + {len(ALLOWED_ENV_EXAMPLE_EXTRAS)} allowed extras."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
