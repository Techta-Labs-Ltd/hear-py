from __future__ import annotations
import time


def record_launch(user_id: str, store: dict) -> dict:
    """Compute launch metadata (first-time vs returning) and the data to persist.

    Returns a dict with keys:
      - isFirstTime, isReturning, launchCount, firstLaunchedAt, lastLaunchedAt
      - save: dict of fields to merge into persistent store
    """
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
