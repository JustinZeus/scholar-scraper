from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from threading import Lock
from time import monotonic


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class SlidingWindowRateLimiter:
    def __init__(
        self,
        *,
        max_attempts: int,
        window_seconds: int,
        now: Callable[[], float] = monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._now = now
        self._attempts: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, key: str) -> RateLimitDecision:
        with self._lock:
            now_value = self._now()
            attempts = self._attempts.get(key)
            if attempts is None:
                return RateLimitDecision(allowed=True)
            self._trim_expired(attempts, now_value)
            if not attempts:
                self._attempts.pop(key, None)
                return RateLimitDecision(allowed=True)
            if len(attempts) >= self._max_attempts:
                retry_after = self._window_seconds - (now_value - attempts[0])
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=max(1, ceil(retry_after)),
                )
            return RateLimitDecision(allowed=True)

    def record_failure(self, key: str) -> None:
        with self._lock:
            now_value = self._now()
            attempts = self._attempts.get(key)
            if attempts is None:
                attempts = deque()
                self._attempts[key] = attempts
            self._trim_expired(attempts, now_value)
            attempts.append(now_value)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def clear_all(self) -> None:
        with self._lock:
            self._attempts.clear()

    def _trim_expired(self, attempts: deque[float], now_value: float) -> None:
        while attempts and now_value - attempts[0] >= self._window_seconds:
            attempts.popleft()
