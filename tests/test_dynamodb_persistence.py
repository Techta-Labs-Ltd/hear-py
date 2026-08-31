from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError

from src.database.dynamo_user import (
    DynamoDbPersistenceAdapter,
    DynamoUserOptions,
    InvalidPersistenceKey,
    PersistenceItemTooLarge,
)


def _adapter_with_mocked_table():
    adapter = object.__new__(DynamoDbPersistenceAdapter)
    adapter.table_name = "hear-service"
    adapter.partition_key_name = "id"
    adapter.attributes_name = "attributes"
    adapter.ttl_attribute = "expiresAt"
    adapter.ttl_days = 180
    adapter.conditional_writes = True
    adapter._table = MagicMock()
    adapter._table.get_item = AsyncMock()
    adapter._table.update_item = AsyncMock()
    adapter._table.update_map_fields = AsyncMock()
    adapter._table.delete_item = AsyncMock()
    return adapter


def test_adapter_uses_hear_service_partition_key_by_default():
    adapter = DynamoDbPersistenceAdapter(DynamoUserOptions(table_name="hear-service"))
    assert adapter.partition_key_name == "id"
    assert adapter._table.partition_key == "id"
    assert adapter.conditional_writes is True


def _envelope(user_id: str = "alexa-user") -> dict:
    return {"context": {"System": {"user": {"userId": user_id}}}}


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
async def test_legacy_item_without_attributes_preserves_version_for_next_save():
    adapter = _adapter_with_mocked_table()
    adapter._table.get_item.return_value = {"stateVersion": 7}
    result = await adapter.get_attributes(_envelope())
    assert result == {"_persistenceVersion": 7}


@pytest.mark.asyncio
async def test_save_bumps_version_and_sets_ttl():
    adapter = _adapter_with_mocked_table()
    adapter._table.update_map_fields.return_value = None
    await adapter.save_attributes(_envelope(), {"pendingAmbiguity": {}, "_persistenceVersion": 4})
    call = adapter._table.update_map_fields.call_args
    assert call.args == ("alexa-user", "attributes", {"pendingAmbiguity": {}})
    updates = call.kwargs["updates"]
    assert updates["stateVersion"] == 5
    assert updates["expiresAt"] > 1700000000
    assert call.kwargs["condition"] == [{"op": "=", "name": "stateVersion", "value": 4}]


@pytest.mark.asyncio
async def test_save_can_disable_conditional_writes_for_shared_event_stream():
    adapter = _adapter_with_mocked_table()
    adapter.conditional_writes = False
    await adapter.save_attributes(
        _envelope(), {"onboardingComplete": True, "_persistenceVersion": 4}
    )
    call = adapter._table.update_item.call_args
    assert call.kwargs["condition"] is None
    assert call.kwargs["updates"]["stateVersion"] == 5


@pytest.mark.asyncio
async def test_concurrent_save_reloads_and_merges_changed_fields(monkeypatch):
    adapter = _adapter_with_mocked_table()
    conflict = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "conflict"}},
        "UpdateItem",
    )
    adapter._table.update_map_fields.side_effect = [conflict, None]
    adapter._table.get_item.return_value = {
        "attributes": {"playCount": 10, "userCity": "London"},
        "stateVersion": 5,
    }
    monkeypatch.setattr("src.database.dynamo_user.settings.HEAR_PERSISTENCE_CONFLICT_BACKOFF_MS", 0)
    await adapter.save_attributes(
        _envelope(),
        {
            "playCount": 3,
            "userCity": "York",
            "_persistenceVersion": 4,
            "_persistenceChangedFields": ["playCount"],
            "_persistenceOriginal": {"playCount": 2},
        },
    )
    second = adapter._table.update_map_fields.call_args_list[1]
    assert second.args == ("alexa-user", "attributes", {"playCount": 11})
    assert second.kwargs["updates"]["stateVersion"] == 6
    assert second.kwargs["condition"] == [{"op": "=", "name": "stateVersion", "value": 5}]


@pytest.mark.asyncio
async def test_oversized_state_is_rejected_before_dynamodb_write(monkeypatch):
    adapter = _adapter_with_mocked_table()
    monkeypatch.setattr("src.database.dynamo_user.settings.HEAR_DDB_ITEM_SIZE_MAX_BYTES", 100)
    with pytest.raises(PersistenceItemTooLarge):
        await adapter.save_attributes(
            _envelope(),
            {"pendingResolution": {"payload": "x" * 200}, "_persistenceVersion": 1},
        )
    adapter._table.update_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_prefixed_keys_are_rejected():
    adapter = _adapter_with_mocked_table()
    with pytest.raises(InvalidPersistenceKey):
        await adapter.get_attributes(_envelope(user_id="session:123"))
