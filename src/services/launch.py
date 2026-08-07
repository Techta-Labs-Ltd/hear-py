from __future__ import annotations
import time


class LaunchTracker:
    __slots__ = ()

    @staticmethod
    def record(user_id: str, store: dict) -> dict:
        launches = (store.get("launchCount") or 0) + 1
        now = int(time.time() * 1000)
        first_launched_at = store.get("firstLaunchedAt") or now
        return {
            "isFirstTime": launches == 1,
            "isReturning": launches > 1,
            "launchCount": launches,
            "firstLaunchedAt": first_launched_at,
            "lastLaunchedAt": now,
            "save": {
                "launchCount": launches,
                "firstLaunchedAt": first_launched_at,
                "lastLaunchedAt": now,
            },
        }


_launch = LaunchTracker()
record_launch = _launch.record
