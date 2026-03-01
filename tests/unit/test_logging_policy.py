from __future__ import annotations

import ast
from pathlib import Path

RAW_LOG_METHODS = {
    "debug",
    "info",
    "warning",
    "error",
    "exception",
    "critical",
}
APP_DIR = Path(__file__).resolve().parents[2] / "app"


def _raw_logger_calls(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if not isinstance(func.value, ast.Name) or func.value.id != "logger":
            continue
        if func.attr not in RAW_LOG_METHODS:
            continue
        violations.append((int(node.lineno), func.attr))
    return violations


def test_app_runtime_uses_structured_log_only() -> None:
    violations: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        for line_number, method in _raw_logger_calls(path):
            relative_path = path.relative_to(APP_DIR.parent)
            violations.append(f"{relative_path}:{line_number} logger.{method}()")
    assert not violations, "raw logger calls found:\n" + "\n".join(violations)
