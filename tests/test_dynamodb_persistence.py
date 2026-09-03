from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError

from src.constants.state import StateSchema
from src.database.dynamo_merge import DynamoConflictMerge
from src.database.dynamo_user import (
    DynamoDbPersistenceAdapter,
    DynamoUserOptions,
    InvalidPersistenceKey,
    PersistenceItemTooLarge,
)


def _adapter_with_mocked_table():
    adapter = object.__new__(DynamoDbPersistenceAdapter)
    adapter.table_name = "hear-listener-state"
    adapter.partition_key_name = "id"
    adapter.sort_key_name = "scope"
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


def _envelope(user_id: str = "alexa-user") -> dict:
    return {"context": {"System": {"user": {"userId": user_id}}}}


def test_adapter_uses_scoped_listener_key_by_default():
    adapter = DynamoDbPersistenceAdapter(DynamoUserOptions(table_name="hear-listener-state"))
    assert adapter.partition_key_name == "id"
    assert adapter.sort_key_name == "scope"
    assert adapter._table.partition_key == "id"
    assert adapter._table.sort_key == "scope"
    assert adapter.conditional_writes is True


def test_play_history_conflict_preserves_both_newest_subjects():
    merged = DynamoConflictMerge.resolve(
        {"playHistory": [{"subjectId": "concurrent"}, {"subjectId": "old"}]},
        {"playHistory": [{"subjectId": "incoming"}, {"subjectId": "old"}]},
        {"playHistory": [{"subjectId": "old"}]},
        ["playHistory"],
    )

    assert [item["subjectId"] for item in merged["playHistory"]] == [
        "incoming",
        "concurrent",
        "old",
    ]


@pytest.mark.asyncio
async def test_user_state_reads_each_scope_with_targeted_consistency():
    adapter = _adapter_with_mocked_table()

    async def read(_user_id, scope, *, consistent):
        values = {
            StateSchema.CORE_SCOPE: {"playbackSpeed": 1.5},
            StateSchema.DIALOG_SCOPE: {"pendingAmbiguity": {"phrase": "pendu"}},
        }
        document = values.get(scope)
        return {"attributes": document, "stateVersion": 4} if document else None

    adapter._table.get_item.side_effect = read
    result = await adapter.get_attributes(_envelope())

    assert result["playbackSpeed"] == 1.5
    assert result["pendingAmbiguity"] == {"phrase": "pendu"}
    assert result["_persistenceVersions"] == {
        "CORE": 4,
        "PLAYBACK": 0,
        "DIALOG": 4,
        "CACHE": 0,
    }
    calls = adapter._table.get_item.call_args_list
    assert calls[0].args == ("alexa-user", "CORE")
    assert calls[0].kwargs == {"consistent": False}
    assert calls[1].kwargs == {"consistent": True}
    assert calls[2].kwargs == {"consistent": True}
    assert calls[3].kwargs == {"consistent": False}


@pytest.mark.asyncio
async def test_missing_item_returns_empty_attributes():
    adapter = _adapter_with_mocked_table()
    adapter._table.get_item.return_value = None
    assert await adapter.get_attributes(_envelope()) == {}


@pytest.mark.asyncio
async def test_adapter_accepts_canonical_listener_persistence_key():
    adapter = _adapter_with_mocked_table()
    adapter._table.get_item.side_effect = [
        {"attributes": {"onboardingComplete": True}, "stateVersion": 2},
        None,
        None,
        None,
    ]
    result = await adapter.get_attributes(
        _envelope(), persistence_key="listener:development:listener-1"
    )
    assert result["onboardingComplete"] is True
    assert all(
        call.args[0] == "listener:development:listener-1"
        for call in adapter._table.get_item.call_args_list
    )


@pytest.mark.asyncio
async def test_first_scope_save_sets_schema_version_ttl_and_condition():
    adapter = _adapter_with_mocked_table()
    await adapter.save_attributes(
        _envelope(),
        {
            "pendingAmbiguity": {"phrase": "pendu"},
            "_persistenceVersions": {},
            "_persistenceChangedFields": ["pendingAmbiguity"],
        },
    )

    call = adapter._table.update_item.call_args
    assert call.args == ("alexa-user", "DIALOG")
    assert call.kwargs["updates"]["attributes"] == {
        "pendingAmbiguity": {"phrase": "pendu"}
    }
    assert call.kwargs["updates"]["schemaVersion"] == 2
    assert call.kwargs["updates"]["stateVersion"] == 1
    assert call.kwargs["updates"]["expiresAt"] > 1700000000
    assert call.kwargs["condition"] == [
        {"op": "not_exists", "name": "stateVersion"}
    ]


@pytest.mark.asyncio
async def test_existing_scope_save_updates_only_changed_fields():
    adapter = _adapter_with_mocked_table()
    await adapter.save_attributes(
        _envelope(),
        {
            "playCount": 3,
            "userCity": "York",
            "_persistenceVersions": {"CORE": 4},
            "_persistenceChangedFields": ["playCount"],
            "_persistenceOriginal": {"playCount": 2},
        },
    )

    call = adapter._table.update_map_fields.call_args
    assert call.args == ("alexa-user", "attributes", {"playCount": 3})
    assert call.kwargs["sort_value"] == "CORE"
    assert call.kwargs["removes"] == []
    assert call.kwargs["updates"]["stateVersion"] == 5
    assert call.kwargs["condition"] == [
        {"op": "=", "name": "stateVersion", "value": 4}
    ]


@pytest.mark.asyncio
async def test_clearing_a_field_uses_remove_instead_of_null():
    adapter = _adapter_with_mocked_table()
    await adapter.save_attributes(
        _envelope(),
        {
            "_persistenceVersions": {"DIALOG": 2},
            "_persistenceChangedFields": ["pendingAmbiguity"],
            "_persistenceOriginal": {"pendingAmbiguity": {"phrase": "pendu"}},
        },
    )

    call = adapter._table.update_map_fields.call_args
    assert call.args[2] == {}
    assert call.kwargs["removes"] == ["pendingAmbiguity"]


@pytest.mark.asyncio
async def test_unrelated_scopes_use_independent_versions():
    adapter = _adapter_with_mocked_table()
    await adapter.save_attributes(
        _envelope(),
        {
            "playbackSpeed": 1.5,
            "activePlayback": {"contentId": "track-1"},
            "_persistenceVersions": {"CORE": 3, "PLAYBACK": 9},
            "_persistenceChangedFields": ["playbackSpeed", "activePlayback"],
        },
    )

    assert adapter._table.update_map_fields.await_count == 2
    calls = adapter._table.update_map_fields.call_args_list
    versions = {call.kwargs["sort_value"]: call.kwargs["updates"]["stateVersion"] for call in calls}
    assert versions == {"CORE": 4, "PLAYBACK": 10}


@pytest.mark.asyncio
async def test_explicit_empty_changed_fields_do_not_write_any_scope():
    adapter = _adapter_with_mocked_table()

    await adapter.save_attributes(
        _envelope(),
        {
            "playbackSpeed": 1.5,
            "activePlayback": {"contentId": "track-1"},
            "_persistenceChangedFields": [],
        },
    )

    adapter._table.update_item.assert_not_awaited()
    adapter._table.update_map_fields.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_removes_all_listener_state_scopes():
    adapter = _adapter_with_mocked_table()

    await adapter.delete_attributes(_envelope())

    assert adapter._table.delete_item.await_count == len(StateSchema.SCOPES)


@pytest.mark.asyncio
async def test_concurrent_save_reloads_and_merges_counter(monkeypatch):
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
    monkeypatch.setattr(
        "src.database.dynamo_user.settings.HEAR_PERSISTENCE_CONFLICT_BACKOFF_MS", 0
    )

    await adapter.save_attributes(
        _envelope(),
        {
            "playCount": 3,
            "userCity": "York",
            "_persistenceVersions": {"CORE": 4},
            "_persistenceChangedFields": ["playCount"],
            "_persistenceOriginal": {"playCount": 2},
        },
    )

    second = adapter._table.update_map_fields.call_args_list[1]
    assert second.args == ("alexa-user", "attributes", {"playCount": 11})
    assert second.kwargs["sort_value"] == "CORE"
    assert second.kwargs["updates"]["stateVersion"] == 6


@pytest.mark.asyncio
async def test_oversized_scope_is_rejected_before_dynamodb_write(monkeypatch):
    adapter = _adapter_with_mocked_table()
    monkeypatch.setattr(
        "src.database.dynamo_user.settings.HEAR_DDB_ITEM_SIZE_MAX_BYTES", 100
    )
    with pytest.raises(PersistenceItemTooLarge):
        await adapter.save_attributes(
            _envelope(),
            {
                "pendingResolution": {"payload": "x" * 200},
                "_persistenceVersions": {"DIALOG": 1},
                "_persistenceChangedFields": ["pendingResolution"],
            },
        )
    adapter._table.update_item.assert_not_awaited()
    adapter._table.update_map_fields.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_prefixed_keys_are_rejected():
    adapter = _adapter_with_mocked_table()
    with pytest.raises(InvalidPersistenceKey):
        await adapter.get_attributes(_envelope(user_id="session:123"))
