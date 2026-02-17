from app.auth.rate_limit import SlidingWindowRateLimiter
from app.auth.security import PasswordService


def test_password_service_hash_and_verify_round_trip() -> None:
    password_service = PasswordService()
    password_hash = password_service.hash_password("example-password")

    assert password_hash.startswith("$argon2id$")
    assert password_service.verify_password(password_hash, "example-password")
    assert not password_service.verify_password(password_hash, "wrong-password")


def test_rate_limiter_enforces_windowed_attempt_budget() -> None:
    clock = {"now": 0.0}
    limiter = SlidingWindowRateLimiter(
        max_attempts=2,
        window_seconds=10,
        now=lambda: clock["now"],
    )
    key = "127.0.0.1:test@example.com"

    assert limiter.check(key).allowed
    limiter.record_failure(key)
    assert limiter.check(key).allowed
    limiter.record_failure(key)

    decision = limiter.check(key)
    assert not decision.allowed
    assert decision.retry_after_seconds == 10

    clock["now"] = 11.0
    assert limiter.check(key).allowed

