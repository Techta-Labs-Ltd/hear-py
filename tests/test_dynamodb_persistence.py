from unittest.mock import MagicMock

import pytest

from src.adapters.dynamodb_persistence import DynamoDbPersistenceAdapter


@pytest.mark.asyncio
async def test_user_state_reads_are_strongly_consistent():
    adapter = object.__new__(DynamoDbPersistenceAdapter)
    adapter.table_name = "hear-service"
    adapter.partition_key_name = "id"
    adapter.attributes_name = "attributes"
    adapter._client = MagicMock()
    adapter._client.get_item.return_value = {
        "Item": {"attributes": {"M": {"pendingAmbiguity": {"M": {}}}}},
    }
    envelope = {
        "context": {
            "System": {"user": {"userId": "alexa-user"}},
        },
    }

    result = await adapter.get_attributes(envelope)

    assert result == {"pendingAmbiguity": {}}
    adapter._client.get_item.assert_called_once_with(
        TableName="hear-service",
        Key={"id": {"S": "alexa-user"}},
        ConsistentRead=True,
    )
