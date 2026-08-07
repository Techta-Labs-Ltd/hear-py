from __future__ import annotations

import asyncio

class BackgroundTaskManager:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

