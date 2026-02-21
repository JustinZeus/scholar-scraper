#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json

from app.db.session import get_session_factory
from app.services.domains.dbops import collect_integrity_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run database integrity checks.")
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Return non-zero exit code if any warning is present.",
    )
    return parser


async def _run() -> dict:
    session_factory = get_session_factory()
    async with session_factory() as db_session:
        return await collect_integrity_report(db_session)


def _exit_code(report: dict, *, strict_warnings: bool) -> int:
    if report.get("status") == "failed":
        return 1
    if strict_warnings and report.get("warnings"):
        return 2
    return 0


def main() -> int:
    args = build_parser().parse_args()

    try:
        report = asyncio.run(_run())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        return 1

    print(json.dumps(report, indent=2))
    return _exit_code(report, strict_warnings=args.strict_warnings)


if __name__ == "__main__":
    raise SystemExit(main())
