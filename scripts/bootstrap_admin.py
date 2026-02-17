from __future__ import annotations

import argparse
import asyncio
import logging
import os

from sqlalchemy import select

from app.auth.security import PasswordService
from app.db.models import User
from app.db.session import get_session_factory
from app.logging_config import configure_logging, parse_redact_fields
from app.settings import settings

configure_logging(
    level=settings.log_level,
    log_format=settings.log_format,
    redact_fields=parse_redact_fields(settings.log_redact_fields),
    include_uvicorn_access=settings.log_uvicorn_access,
)

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or update the initial admin user.")
    parser.add_argument("--email", default=os.getenv("BOOTSTRAP_ADMIN_EMAIL"))
    parser.add_argument("--password", default=os.getenv("BOOTSTRAP_ADMIN_PASSWORD"))
    parser.add_argument(
        "--force-password",
        action="store_true",
        default=os.getenv("BOOTSTRAP_ADMIN_FORCE_PASSWORD", "0") in {"1", "true", "yes"},
        help="When user exists, replace password with provided value.",
    )
    return parser


async def bootstrap_admin(*, email: str | None, password: str | None, force_password: bool) -> int:
    if not email:
        logger.info(
            "admin.bootstrap_skipped",
            extra={"event": "admin.bootstrap_skipped"},
        )
        return 0
    if not password:
        logger.error(
            "admin.bootstrap_missing_password",
            extra={"event": "admin.bootstrap_missing_password"},
        )
        return 1

    normalized_email = email.strip().lower()
    if not normalized_email:
        logger.error(
            "admin.bootstrap_invalid_email",
            extra={"event": "admin.bootstrap_invalid_email"},
        )
        return 1
    if len(password.strip()) < 8:
        logger.error(
            "admin.bootstrap_invalid_password",
            extra={"event": "admin.bootstrap_invalid_password"},
        )
        return 1

    session_factory = get_session_factory()
    password_service = PasswordService()
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.email == normalized_email))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                email=normalized_email,
                password_hash=password_service.hash_password(password.strip()),
                is_admin=True,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            logger.info(
                "admin.bootstrap_created",
                extra={"event": "admin.bootstrap_created", "email": normalized_email},
            )
            return 0

        changed = False
        if not user.is_admin:
            user.is_admin = True
            changed = True
        if not user.is_active:
            user.is_active = True
            changed = True
        if force_password:
            user.password_hash = password_service.hash_password(password.strip())
            changed = True

        if changed:
            await session.commit()
            logger.info(
                "admin.bootstrap_updated",
                extra={"event": "admin.bootstrap_updated", "email": normalized_email},
            )
        else:
            logger.info(
                "admin.bootstrap_already_configured",
                extra={"event": "admin.bootstrap_already_configured", "email": normalized_email},
            )
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(
        bootstrap_admin(
            email=args.email,
            password=args.password,
            force_password=args.force_password,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
