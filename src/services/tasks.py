from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class BackgroundTaskManager:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def schedule(self, coroutine, label: str = "background") -> None:
        try:
            task = asyncio.ensure_future(coroutine)
        except RuntimeError:
            return
        self._tasks.add(task)
        task.add_done_callback(
            lambda finished: self._complete(finished, label)
        )

    def _complete(self, task: asyncio.Task, label: str) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.warning("Hear: background task %s failed: %s", label, error)


background_tasks = BackgroundTaskManager()


def run_background(coroutine, label: str = "background") -> None:
    background_tasks.schedule(coroutine, label)
