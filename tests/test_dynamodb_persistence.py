from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.dynamodb_persistence import (
    DynamoDbPersistenceAdapter,
    InvalidPersistenceKey,
)


def _adapter_with_mocked_table():
    adapter = object.__new__(DynamoDbPersistenceAdapter)
    adapter.table_name = "hear-service"
    adapter.partition_key_name = "id"
    adapter.attributes_name = "attributes"
    adapter.ttl_attribute = "expiresAt"
    adapter.ttl_days = 180
    adapter._table = MagicMock()
    adapter._table.get_item = AsyncMock()
    adapter._table.update_item = AsyncMock()
    adapter._table.delete_item = AsyncMock()
    return adapter


def _envelope(user_id: str = "alexa-user") -> dict:
    return {
        "context": {
            "System": {"user": {"userId": user_id}},
        },
    }


@pytest.mark.asyncio
async def test_user_state_reads_are_strongly_consistent():
    adapter = _adapter_with_mocked_table()
    adapter._table.get_item.return_value = {
        "attributes": {"pendingAmbiguity": {}},
        "stateVersion": 4,
    }

    result = await adapter.get_attributes(_envelope())

    assert result == {"pendingAmbiguity": {}, "_persistenceVersion": 4}
    adapter._table.get_item.assert_called_once_with("alexa-user")


@pytest.mark.asyncio
async def test_missing_item_returns_empty_attributes():
    adapter = _adapter_with_mocked_table()
    adapter._table.get_item.return_value = None

    result = await adapter.get_attributes(_envelope())

    assert result == {}


@pytest.mark.asyncio
async def test_save_bumps_version_and_sets_ttl():
    adapter = _adapter_with_mocked_table()
    adapter._table.update_item.return_value = None

    await adapter.save_attributes(
        _envelope(),
        {"pendingAmbiguity": {}, "_persistenceVersion": 4},
    )

    call = adapter._table.update_item.call_args
    assert call.args == ("alexa-user",)
    updates = call.kwargs["updates"]
    assert updates["attributes"] == {"pendingAmbiguity": {}}
    assert updates["stateVersion"] == 5
    assert updates["expiresAt"] > 1700000000
    assert call.kwargs["condition"] == [
        {"op": "=", "name": "stateVersion", "value": 4},
    ]


@pytest.mark.asyncio
async def test_session_prefixed_keys_are_rejected():
    adapter = _adapter_with_mocked_table()

    with pytest.raises(InvalidPersistenceKey):
        await adapter.get_attributes(_envelope(user_id="session:123"))
