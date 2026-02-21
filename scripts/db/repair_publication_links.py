#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json

from app.db.session import get_session_factory
from app.services.domains.dbops import run_publication_link_repair


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Repair scholar-publication links for a user with audit logging.",
    )
    parser.add_argument("--user-id", type=int, required=True, help="Target user ID.")
    parser.add_argument(
        "--scholar-profile-id",
        type=int,
        action="append",
        default=[],
        help="Optional scholar_profile_id filter. Repeat for multiple values.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default is dry-run.")
    parser.add_argument(
        "--gc-orphan-publications",
        action="store_true",
        help="Delete publications with zero links after cleanup.",
    )
    parser.add_argument(
        "--requested-by",
        default="",
        help="Operator identifier for audit logs (email/name/ticket).",
    )
    return parser


async def _run(args: argparse.Namespace) -> dict:
    session_factory = get_session_factory()
    async with session_factory() as db_session:
        return await run_publication_link_repair(
            db_session,
            user_id=args.user_id,
            scholar_profile_ids=args.scholar_profile_id,
            dry_run=not args.apply,
            gc_orphan_publications=args.gc_orphan_publications,
            requested_by=args.requested_by,
        )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
