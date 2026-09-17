from __future__ import annotations

import time

import pytest

from src.models.user import User
from src.services.notification_recipient import AlexaNotificationRecipientDirectory


class FakeRecipientTable:
    partition_key = "id"

    def __init__(self, items: list[dict] | None = None) -> None:
        self.items = list(items or [])
        self.batch_keys: list[tuple[str, str]] = []
        self.update_calls: list[dict] = []

    async def batch_get_items(self, keys, *, consistent=True):
        assert consistent is True
        self.batch_keys = list(keys)
        requested = {key[0] for key in keys}
        return [item for item in self.items if item["id"] in requested]

    async def update_item(self, partition, scope, **options):
        self.update_calls.append(
            {"partition": partition, "scope": scope, **options}
        )


@pytest.mark.asyncio
async def test_recipient_directory_conditionally_refreshes_and_batch_reads_current_addresses():
    now = int(time.time())
    listener_one = User.canonical_persistence_key("listener-1")
    listener_two = User.canonical_persistence_key("listener-2")
    table = FakeRecipientTable(
        [
            {
                "id": listener_one,
                "scope": "NOTIFICATION_RECIPIENT",
                "alexaUserId": "amzn1.ask.account.current",
                "expiresAt": now + 60,
            },
            {
                "id": listener_two,
                "scope": "NOTIFICATION_RECIPIENT",
                "alexaUserId": "amzn1.ask.account.expired",
                "expiresAt": now - 1,
            },
        ]
    )
    directory = AlexaNotificationRecipientDirectory(table)

    assert await directory.remember(
        listener_id="listener-1",
        alexa_user_id="amzn1.ask.account.current",
        device_id="device-1",
        locale="en-GB",
    )
    assert table.update_calls[0]["partition"] == listener_one
    assert table.update_calls[0]["scope"] == "NOTIFICATION_RECIPIENT"
    assert table.update_calls[0]["updates"]["deviceId"] == "device-1"
    assert table.update_calls[0]["updates"]["locale"] == "en-GB"
    assert table.update_calls[0]["condition"][0]["op"] == "or"

    recipients = await directory.get_many(["listener-1", "listener-2", "listener-1"])

    assert table.batch_keys == [
        (listener_one, "NOTIFICATION_RECIPIENT"),
        (listener_two, "NOTIFICATION_RECIPIENT"),
    ]
    assert recipients == {
        "listener-1": {
            "id": listener_one,
            "scope": "NOTIFICATION_RECIPIENT",
            "alexaUserId": "amzn1.ask.account.current",
            "expiresAt": now + 60,
        }
    }
