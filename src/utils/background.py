from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_BACKGROUND_TASKS: set = set()


def run_background(coro, label: str = "background") -> None:
    """Schedule a best-effort coroutine without awaiting it.

    Unlike a bare ``asyncio.ensure_future``, this holds a strong reference to
    the task until it finishes (so it is not garbage-collected mid-flight) and
    attaches a done callback that logs any exception instead of letting it be
    swallowed silently.
    """
    try:
        task = asyncio.ensure_future(coro)
    except RuntimeError:
        return

    _BACKGROUND_TASKS.add(task)

    def _on_done(finished: asyncio.Task) -> None:
        _BACKGROUND_TASKS.discard(finished)
        if finished.cancelled():
            return
        exc = finished.exception()
        if exc is not None:
            logger.warning("Hear: background task %s failed: %s", label, exc)

    task.add_done_callback(_on_done)
