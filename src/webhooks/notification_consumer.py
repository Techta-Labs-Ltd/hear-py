from __future__ import annotations

import asyncio
import json

import httpx

from src.services.notifications import (
    ingest_notification_payload,
    update_notification_delivery_status,
)
from src.services.proactive_notifications import send_proactive_notification


def handler(event: dict, context=None) -> dict:
    async def run() -> dict:
        failures = []
        for record in event.get("Records") or []:
            try:
                payload = json.loads(record.get("body") or "{}")
                items = await ingest_notification_payload(payload)
                semaphore = asyncio.Semaphore(10)

                async def deliver(item: dict, client: httpx.AsyncClient) -> None:
                    async with semaphore:
                        delivered = await send_proactive_notification(item, client)
                        await update_notification_delivery_status(
                            item["alexaUserId"],
                            item["notificationId"],
                            "sent" if delivered else "not_configured",
                        )

                async with httpx.AsyncClient(timeout=10.0) as client:
                    await asyncio.gather(*(deliver(item, client) for item in items))
            except Exception:
                failures.append({"itemIdentifier": record.get("messageId")})
        return {"batchItemFailures": failures}

    return asyncio.run(run())
