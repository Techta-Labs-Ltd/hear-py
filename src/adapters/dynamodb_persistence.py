from __future__ import annotations
import time
import boto3
from botocore.exceptions import ClientError
from .persistence_user_id import resolve_persistence_user_id
from config import settings


def _to_attr(value):
    if value is None:
        return {"NULL": True}
    if isinstance(value, str):
        return {"NULL": True} if value == "" else {"S": value}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, (int, float)):
        return {"N": str(value)} if value == value else {"NULL": True}
    if isinstance(value, list):
        return {"L": [_to_attr(v) for v in value]}
    if isinstance(value, dict):
        return {"M": {k: _to_attr(v) for k, v in value.items()}}
    return {"S": str(value)}


def _from_attr(attr):
    if not attr or not isinstance(attr, dict):
        return None
    if "NULL" in attr:
        return None
    if "S" in attr:
        return attr["S"]
    if "N" in attr:
        return float(attr["N"]) if "." in str(attr["N"]) else int(attr["N"])
    if "BOOL" in attr:
        return attr["BOOL"]
    if "L" in attr:
        return [_from_attr(v) for v in attr["L"]]
    if "M" in attr:
        return {k: _from_attr(v) for k, v in attr["M"].items()}
    return None


class DynamoDbPersistenceAdapter:
    def __init__(
        self,
        table_name: str,
        partition_key_name: str = "id",
        attributes_name: str = "attributes",
        region: str | None = None,
        ttl_attribute: str = "expiresAt",
        ttl_days: int | None = None,
    ) -> None:
        if not table_name:
            raise ValueError("DynamoDbPersistenceAdapter: table_name is required")
        self.table_name = table_name
        self.partition_key_name = partition_key_name
        self.attributes_name = attributes_name
        self.ttl_attribute = ttl_attribute
        self.ttl_days = ttl_days or settings.HEAR_PERSISTENCE_TTL_DAYS
        self._client = boto3.client("dynamodb", region_name=region or settings.ddb_region)

    def _key(self, request_envelope: dict) -> dict:
        user_id = resolve_persistence_user_id(request_envelope)
        return {self.partition_key_name: {"S": user_id}}

    async def get_attributes(self, request_envelope: dict) -> dict:
        try:
            resp = self._client.get_item(
                TableName=self.table_name,
                Key=self._key(request_envelope),
                ConsistentRead=False,
            )
            item = resp.get("Item")
            if not item or self.attributes_name not in item:
                return {}
            return _from_attr(item[self.attributes_name]) or {}
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                return {}
            raise

    async def save_attributes(self, request_envelope: dict, attributes: dict) -> None:
        expires_at = int(time.time()) + (self.ttl_days or 180) * 86400
        item = {
            **self._key(request_envelope),
            self.attributes_name: _to_attr(attributes or {}),
            self.ttl_attribute: {"N": str(expires_at)},
        }
        self._client.put_item(TableName=self.table_name, Item=item)

    async def delete_attributes(self, request_envelope: dict) -> None:
        self._client.delete_item(
            TableName=self.table_name,
            Key=self._key(request_envelope),
        )


def build_dynamo_adapter(table_name: str | None = None, region: str | None = None) -> DynamoDbPersistenceAdapter:
    return DynamoDbPersistenceAdapter(
        table_name=table_name or settings.dynamo_table,
        region=region or settings.ddb_region,
        ttl_days=settings.HEAR_PERSISTENCE_TTL_DAYS,
    )
