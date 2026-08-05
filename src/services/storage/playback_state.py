from __future__ import annotations

import asyncio
import boto3

from config import settings


class PlaybackStateRepository:
    def __init__(self, table_name: str = "", region: str = "") -> None:
        self.table_name = table_name.strip()
        self.region = region.strip()
        self._memory: dict[str, dict] = {}
        self._dynamodb = None

    def _resolved_table_name(self) -> str:
        return self.table_name or str(
            getattr(settings, "DYNAMO_PLAYBACK_STATE_TABLE", "") or ""
        ).strip()

    def _resolved_region(self) -> str:
        return (
            self.region
            or getattr(settings, "HEAR_DDB_REGION", None)
            or getattr(settings, "AWS_REGION", None)
            or "eu-west-1"
        )

    def _table(self):
        if self._dynamodb is None:
            self._dynamodb = boto3.resource(
                "dynamodb",
                region_name=self._resolved_region(),
            )
        return self._dynamodb.Table(self._resolved_table_name())

    async def get(self, user_id: str) -> dict | None:
        if not user_id:
            return None
        if not self._resolved_table_name():
            return self._memory.get(user_id)
        try:
            response = await asyncio.to_thread(
                self._table().get_item, Key={"alexaUserId": user_id}
            )
            return response.get("Item")
        except Exception:
            return None

    async def set(self, user_id: str, fields: dict) -> dict | None:
        if not user_id or not isinstance(fields, dict):
            return None
        if not self._resolved_table_name():
            existing = await self.get(user_id) or {}
            state = {"alexaUserId": user_id, **existing, **fields}
            self._memory[user_id] = state
            return state
        try:
            names = {f"#f{index}": key for index, key in enumerate(fields)}
            values = {f":v{index}": value for index, value in enumerate(fields.values())}
            response = await asyncio.to_thread(
                self._table().update_item,
                Key={"alexaUserId": user_id},
                UpdateExpression="SET " + ", ".join(
                    f"#f{index} = :v{index}" for index in range(len(fields))
                ),
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
            return response.get("Attributes")
        except Exception:
            return None

    async def clear(self, user_id: str) -> None:
        if not user_id:
            return
        if not self._resolved_table_name():
            self._memory.pop(user_id, None)
            return
        try:
            await asyncio.to_thread(
                self._table().delete_item, Key={"alexaUserId": user_id}
            )
        except Exception:
            return

    def reset_memory(self) -> None:
        self._memory.clear()


playback_state_repository = PlaybackStateRepository()


async def get_state(alexa_user_id: str) -> dict | None:
    return await playback_state_repository.get(alexa_user_id)


async def set_state(alexa_user_id: str, fields: dict) -> dict | None:
    return await playback_state_repository.set(alexa_user_id, fields)


async def clear_state(alexa_user_id: str) -> None:
    await playback_state_repository.clear(alexa_user_id)


def reset_memory_store_for_tests() -> None:
    playback_state_repository.reset_memory()
