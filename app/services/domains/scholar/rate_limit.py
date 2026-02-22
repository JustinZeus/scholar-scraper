from __future__ import annotations

import asyncio
import time

_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0


async def wait_for_scholar_slot(*, min_interval_seconds: float) -> None:
    global _LAST_REQUEST_AT
    interval = max(float(min_interval_seconds), 0.0)
    async with _REQUEST_LOCK:
        elapsed = time.monotonic() - _LAST_REQUEST_AT
        remaining = interval - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)
        _LAST_REQUEST_AT = time.monotonic()
