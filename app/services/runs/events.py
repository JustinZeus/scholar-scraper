import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from app.logging_utils import structured_log

logger = logging.getLogger(__name__)


class RunEventPublisher:
    def __init__(self) -> None:
        # Maps run_id to a set of subscriber queues
        self._subscribers: dict[int, set[asyncio.Queue]] = {}

    def subscribe(self, run_id: int) -> asyncio.Queue:
        if run_id not in self._subscribers:
            self._subscribers[run_id] = set()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._subscribers[run_id].add(queue)
        structured_log(
            logger,
            "debug",
            "runs.event_subscriber_added",
            run_id=run_id,
            subscriber_count=len(self._subscribers[run_id]),
        )
        return queue

    def unsubscribe(self, run_id: int, queue: asyncio.Queue) -> None:
        if run_id in self._subscribers:
            self._subscribers[run_id].discard(queue)
            if not self._subscribers[run_id]:
                self._subscribers.pop(run_id, None)

    async def publish(self, run_id: int, event_type: str, data: dict[str, Any]) -> None:
        if run_id not in self._subscribers:
            return

        message = {"type": event_type, "data": data}

        # Fan-out to all active subscribers for this run
        for queue in list(self._subscribers[run_id]):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                structured_log(
                    logger,
                    "warning",
                    "runs.event_subscriber_queue_full",
                    run_id=run_id,
                )


run_events = RunEventPublisher()


async def event_generator(run_id: int) -> AsyncGenerator[str, None]:
    queue = run_events.subscribe(run_id)
    try:
        while True:
            # Wait for a new event
            message = await queue.get()
            # Server-Sent Events format: "event: <type>\ndata: <json>\n\n"
            event_type = message["type"]
            data_str = json.dumps(message["data"])
            yield f"event: {event_type}\ndata: {data_str}\n\n"
    except asyncio.CancelledError:
        structured_log(
            logger,
            "debug",
            "runs.event_stream_disconnected",
            run_id=run_id,
        )
        raise
    finally:
        run_events.unsubscribe(run_id, queue)
