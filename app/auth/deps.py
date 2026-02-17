from __future__ import annotations

from functools import lru_cache

from app.auth.rate_limit import SlidingWindowRateLimiter
from app.auth.security import PasswordService
from app.auth.service import AuthService
from app.settings import settings


@lru_cache
def get_password_service() -> PasswordService:
    return PasswordService()


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService(password_service=get_password_service())


@lru_cache
def get_login_rate_limiter() -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(
        max_attempts=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )

