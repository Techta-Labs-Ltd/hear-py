from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import boto3
from botocore.config import Config


class DynamoExpressions:
    _lock = threading.Lock()
    _clients: dict[str, Any] = {}

    @staticmethod
    def get_client(region: str | None = None) -> Any:
        key = region or ""
        client = DynamoExpressions._clients.get(key)
        if client is None:
            with DynamoExpressions._lock:
                client = DynamoExpressions._clients.get(key)
                if client is None:
                    client = boto3.client(
                        "dynamodb",
                        region_name=region,
                        config=Config(
                            connect_timeout=1, read_timeout=2, retries={"max_attempts": 0}
                        ),
                    )
                    DynamoExpressions._clients[key] = client
        return client

    @staticmethod
    def encode_value(value: Any) -> dict:
        if value is None:
            return {"NULL": True}
        if isinstance(value, str):
            return {"NULL": True} if value == "" else {"S": value}
        if isinstance(value, bool):
            return {"BOOL": value}
        if isinstance(value, (int, float)):
            return {"N": str(value)} if value == value else {"NULL": True}
        if isinstance(value, list):
            return {"L": [DynamoExpressions.encode_value(v) for v in value]}
        if isinstance(value, dict):
            return {"M": {k: DynamoExpressions.encode_value(v) for k, v in value.items()}}
        return {"S": str(value)}

    @staticmethod
    def decode_value(attr: dict | None) -> Any:
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
            return [DynamoExpressions.decode_value(v) for v in attr["L"]]
        if "M" in attr:
            return {k: DynamoExpressions.decode_value(v) for k, v in attr["M"].items()}
        return None

    @staticmethod
    def decode_item(item: dict) -> dict:
        return {k: DynamoExpressions.decode_value(v) for k, v in item.items()}

    @staticmethod
    def item_bytes(item: dict) -> int:
        if not item:
            return 0
        return len(json.dumps(item, separators=(",", ":")))

    @staticmethod
    def eq(name: str, value: Any) -> dict:
        return {"op": "=", "name": name, "value": value}

    @staticmethod
    def not_exists(name: str) -> dict:
        return {"op": "not_exists", "name": name}

    @staticmethod
    def build_condition(rules: list[dict], start_index: int = 0) -> tuple[str, dict, dict]:
        expressions = []
        names: dict[str, str] = {}
        values: dict[str, dict] = {}
        index = start_index
        for rule in rules or []:
            if rule.get("op") == "or":
                inner, inner_names, inner_values = DynamoExpressions.build_condition(
                    rule["rules"], start_index=index
                )
                expressions.append(f"({inner.replace(' AND ', ' OR ')})")
                names.update(inner_names)
                values.update(inner_values)
                index += 100
                continue
            op = rule["op"]
            name = rule["name"]
            name_key = f"#f{index}"
            names[name_key] = name
            if op == "exists":
                expressions.append(f"attribute_exists({name_key})")
            elif op == "not_exists":
                expressions.append(f"attribute_not_exists({name_key})")
            elif op == "contains":
                value_key = f":v{index}"
                values[value_key] = DynamoExpressions.encode_value(rule["value"])
                expressions.append(f"contains({name_key}, {value_key})")
            elif op == "begins_with":
                value_key = f":v{index}"
                values[value_key] = DynamoExpressions.encode_value(rule["value"])
                expressions.append(f"begins_with({name_key}, {value_key})")
            elif op == "IN":
                values[f":v{index}"] = DynamoExpressions.encode_value(rule["value"])
                expressions.append(
                    f"{name_key} IN ({', '.join((f':in{index}_{pos}' for pos in range(len(rule['value']))))})"
                )
                for pos, raw in enumerate(rule["value"]):
                    values[f":in{index}_{pos}"] = DynamoExpressions.encode_value(raw)
            else:
                value_key = f":v{index}"
                values[value_key] = DynamoExpressions.encode_value(rule["value"])
                operator = {
                    "=": "=",
                    "<>": "<>",
                    ">": ">",
                    ">=": ">=",
                    "<": "<",
                    "<=": "<=",
                }[op]
                expressions.append(f"{name_key} {operator} {value_key}")
            index += 1
        return (" AND ".join(expressions), names, values)


class DynamoTable:
    def __init__(
        self,
        table_name: str,
        partition_key: str = "id",
        sort_key: str | None = None,
        region: str | None = None,
    ) -> None:
        if not table_name:
            raise ValueError("DynamoTable: table_name is required")
        self.table_name = table_name
        self.partition_key = partition_key
        self.sort_key = sort_key
        self._region = region
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = DynamoExpressions.get_client(self._region)
        return self._client

    def _request(self, operation: str, params: dict):
        return getattr(self.client, operation)(**params)

    def _key(self, partition_value: Any, sort_value: Any = None) -> dict:
        key = {self.partition_key: DynamoExpressions.encode_value(partition_value)}
        if self.sort_key and sort_value is not None:
            key[self.sort_key] = DynamoExpressions.encode_value(sort_value)
        return key

    async def get_item(
        self, partition_value: Any, sort_value: Any = None, *, consistent: bool = True
    ) -> dict | None:
        params = {
            "TableName": self.table_name,
            "Key": self._key(partition_value, sort_value),
            "ConsistentRead": consistent,
        }
        response = await asyncio.to_thread(self._request, "get_item", params)
        item = response.get("Item")
        return DynamoExpressions.decode_item(item) if item else None

    async def batch_get_items(
        self,
        keys: list[tuple[Any, Any]],
        *,
        consistent: bool = True,
    ) -> list[dict]:
        """Read up to 100 keyed items at a time, retrying DynamoDB throttling hints."""
        if not keys:
            return []
        items: list[dict] = []
        for start in range(0, len(keys), 100):
            request_keys = [self._key(partition, sort) for partition, sort in keys[start : start + 100]]
            pending = request_keys
            for attempt in range(4):
                response = await asyncio.to_thread(
                    self._request,
                    "batch_get_item",
                    {
                        "RequestItems": {
                            self.table_name: {
                                "Keys": pending,
                                "ConsistentRead": consistent,
                            }
                        }
                    },
                )
                items.extend(
                    DynamoExpressions.decode_item(item)
                    for item in response.get("Responses", {}).get(self.table_name, [])
                )
                pending = response.get("UnprocessedKeys", {}).get(self.table_name, {}).get("Keys", [])
                if not pending:
                    break
                await asyncio.sleep(0.05 * (2**attempt))
            if pending:
                raise RuntimeError("DynamoDB batch recipient lookup remained unprocessed")
        return items

    async def update_item(
        self,
        partition_value: Any,
        sort_value: Any = None,
        **options,
    ) -> dict | None:
        updates = options.get("updates")
        removes = options.get("removes")
        condition = options.get("condition")
        return_old = bool(options.get("return_old"))
        set_clauses = []
        names: dict[str, str] = {}
        values: dict[str, dict] = {}
        for index, (field, raw) in enumerate((updates or {}).items()):
            name_key = f"#u{index}"
            value_key = f":u{index}"
            names[name_key] = field
            values[value_key] = DynamoExpressions.encode_value(raw)
            set_clauses.append(f"{name_key} = {value_key}")
        remove_clauses = []
        for index, field in enumerate(removes or []):
            name_key = f"#r{index}"
            names[name_key] = field
            remove_clauses.append(name_key)
        expression_parts = []
        if set_clauses:
            expression_parts.append(f"SET {', '.join(set_clauses)}")
        if remove_clauses:
            expression_parts.append(f"REMOVE {', '.join(remove_clauses)}")
        if not expression_parts:
            raise ValueError("update_item requires updates or removes")
        params: dict[str, Any] = {
            "TableName": self.table_name,
            "Key": self._key(partition_value, sort_value),
            "UpdateExpression": " ".join(expression_parts),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
            "ReturnValues": "ALL_OLD" if return_old else "NONE",
        }
        if condition:
            condition_expression, condition_names, condition_values = (
                DynamoExpressions.build_condition(condition, start_index=1000)
            )
            params["ConditionExpression"] = condition_expression
            params["ExpressionAttributeNames"].update(condition_names)
            params["ExpressionAttributeValues"].update(condition_values)
        response = await asyncio.to_thread(self._request, "update_item", params)
        old = response.get("Attributes")
        return DynamoExpressions.decode_item(old) if old else None

    async def update_map_fields(
        self,
        partition_value: Any,
        map_name: str,
        fields: dict[str, Any],
        *,
        sort_value: Any = None,
        removes: list[str] | tuple[str, ...] | None = None,
        updates: dict[str, Any],
        condition: list[dict] | None = None,
    ) -> None:
        names = {"#document": map_name}
        values: dict[str, dict] = {}
        clauses = []
        for index, (field, raw) in enumerate(fields.items()):
            name_key = f"#d{index}"
            value_key = f":d{index}"
            names[name_key] = field
            values[value_key] = DynamoExpressions.encode_value(raw)
            clauses.append(f"#document.{name_key} = {value_key}")
        remove_clauses = []
        for index, field in enumerate(removes or [], start=len(fields)):
            name_key = f"#r{index}"
            names[name_key] = field
            remove_clauses.append(f"#document.{name_key}")
        offset = len(fields)
        for index, (field, raw) in enumerate(updates.items(), start=offset):
            name_key = f"#u{index}"
            value_key = f":u{index}"
            names[name_key] = field
            values[value_key] = DynamoExpressions.encode_value(raw)
            clauses.append(f"{name_key} = {value_key}")
        expression_parts = []
        if clauses:
            expression_parts.append(f"SET {', '.join(clauses)}")
        if remove_clauses:
            expression_parts.append(f"REMOVE {', '.join(remove_clauses)}")
        params: dict[str, Any] = {
            "TableName": self.table_name,
            "Key": self._key(partition_value, sort_value),
            "UpdateExpression": " ".join(expression_parts),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
        }
        if condition:
            expression, condition_names, condition_values = DynamoExpressions.build_condition(
                condition, start_index=1000
            )
            params["ConditionExpression"] = expression
            params["ExpressionAttributeNames"].update(condition_names)
            params["ExpressionAttributeValues"].update(condition_values)
        await asyncio.to_thread(self._request, "update_item", params)

    def transaction_update_item(
        self,
        partition_value: Any,
        sort_value: Any,
        updates: dict[str, Any],
        *,
        condition: list[dict] | None = None,
    ) -> dict:
        set_clauses = []
        names: dict[str, str] = {}
        values: dict[str, dict] = {}
        for index, (field, raw) in enumerate(updates.items()):
            name_key = f"#u{index}"
            value_key = f":u{index}"
            names[name_key] = field
            values[value_key] = DynamoExpressions.encode_value(raw)
            set_clauses.append(f"{name_key} = {value_key}")
        params: dict[str, Any] = {
            "TableName": self.table_name,
            "Key": self._key(partition_value, sort_value),
            "UpdateExpression": f"SET {', '.join(set_clauses)}",
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
        }
        if condition:
            expression, condition_names, condition_values = DynamoExpressions.build_condition(
                condition, start_index=1000
            )
            params["ConditionExpression"] = expression
            params["ExpressionAttributeNames"].update(condition_names)
            params["ExpressionAttributeValues"].update(condition_values)
        return {"Update": params}

    def transaction_map_update(
        self,
        partition_value: Any,
        map_name: str,
        fields: dict[str, Any],
        *,
        sort_value: Any,
        removes: list[str] | tuple[str, ...] | None,
        updates: dict[str, Any],
        condition: list[dict] | None = None,
    ) -> dict:
        names = {"#document": map_name}
        values: dict[str, dict] = {}
        clauses = []
        for index, (field, raw) in enumerate(fields.items()):
            name_key = f"#d{index}"
            value_key = f":d{index}"
            names[name_key] = field
            values[value_key] = DynamoExpressions.encode_value(raw)
            clauses.append(f"#document.{name_key} = {value_key}")
        remove_clauses = []
        for index, field in enumerate(removes or [], start=len(fields)):
            name_key = f"#r{index}"
            names[name_key] = field
            remove_clauses.append(f"#document.{name_key}")
        for index, (field, raw) in enumerate(updates.items(), start=len(fields)):
            name_key = f"#u{index}"
            value_key = f":u{index}"
            names[name_key] = field
            values[value_key] = DynamoExpressions.encode_value(raw)
            clauses.append(f"{name_key} = {value_key}")
        expression_parts = []
        if clauses:
            expression_parts.append(f"SET {', '.join(clauses)}")
        if remove_clauses:
            expression_parts.append(f"REMOVE {', '.join(remove_clauses)}")
        params: dict[str, Any] = {
            "TableName": self.table_name,
            "Key": self._key(partition_value, sort_value),
            "UpdateExpression": " ".join(expression_parts),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
        }
        if condition:
            expression, condition_names, condition_values = DynamoExpressions.build_condition(
                condition, start_index=1000
            )
            params["ConditionExpression"] = expression
            params["ExpressionAttributeNames"].update(condition_names)
            params["ExpressionAttributeValues"].update(condition_values)
        return {"Update": params}

    def transaction_put_item(
        self, item: dict[str, Any], *, condition: list[dict] | None = None
    ) -> dict:
        params: dict[str, Any] = {
            "TableName": self.table_name,
            "Item": {key: DynamoExpressions.encode_value(value) for key, value in item.items()},
        }
        if condition:
            expression, names, values = DynamoExpressions.build_condition(condition)
            params["ConditionExpression"] = expression
            params["ExpressionAttributeNames"] = names
            if values:
                params["ExpressionAttributeValues"] = values
        return {"Put": params}

    async def transact_write(self, operations: list[dict]) -> None:
        if not operations:
            return
        if len(operations) > 25:
            raise ValueError("DynamoDB transactions support at most 25 operations")
        await asyncio.to_thread(
            self._request,
            "transact_write_items",
            {"TransactItems": operations},
        )

    async def delete_item(
        self,
        partition_value: Any,
        sort_value: Any = None,
        *,
        condition: list[dict] | None = None,
    ) -> None:
        params: dict[str, Any] = {
            "TableName": self.table_name,
            "Key": self._key(partition_value, sort_value),
        }
        if condition:
            expression, names, values = DynamoExpressions.build_condition(condition)
            params["ConditionExpression"] = expression
            params["ExpressionAttributeNames"] = names
            params["ExpressionAttributeValues"] = values
        await asyncio.to_thread(self._request, "delete_item", params)

    async def query(
        self,
        partition_value: Any,
        **options,
    ) -> dict:
        filters = options.get("filters")
        limit = options.get("limit")
        exclusive_start_key = options.get("exclusive_start_key")
        consistent = bool(options.get("consistent"))
        ascending = options.get("ascending")
        index_name = options.get("index_name")
        partition_key = options.get("partition_key") or self.partition_key
        params: dict[str, Any] = {
            "TableName": self.table_name,
            "KeyConditionExpression": "#partitionKey = :pk",
            "ExpressionAttributeNames": {"#partitionKey": partition_key},
            "ExpressionAttributeValues": {":pk": DynamoExpressions.encode_value(partition_value)},
            "ConsistentRead": consistent,
        }
        if index_name:
            params["IndexName"] = str(index_name)
        if filters:
            filter_expression, names, values = DynamoExpressions.build_condition(filters)
            params["FilterExpression"] = filter_expression
            params["ExpressionAttributeNames"].update(names)
            params["ExpressionAttributeValues"] = {
                **params["ExpressionAttributeValues"],
                **values,
            }
        if limit is not None:
            params["Limit"] = limit
        if exclusive_start_key:
            params["ExclusiveStartKey"] = exclusive_start_key
        if ascending is not None:
            params["ScanIndexForward"] = ascending
        response = await asyncio.to_thread(self._request, "query", params)
        return {
            "items": [DynamoExpressions.decode_item(item) for item in response.get("Items", [])],
            "last_evaluated_key": response.get("LastEvaluatedKey"),
            "count": response.get("Count", 0),
        }
