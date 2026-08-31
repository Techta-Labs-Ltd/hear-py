from __future__ import annotations

import logging

from config import settings
from src.alexa.runtime import AsyncSkill
from src.container import ApplicationContainer
from src.database.dynamo_user import DynamoUserSupport
from src.database.persistence import MemoryPersistenceAdapter
from src.registry import RouteRegistry


class Application:
    logger = logging.getLogger(__name__)

    @staticmethod
    def build_persistence_adapter():
        """Build the configured persistence adapter with a safe local fallback."""
        driver = (settings.HEAR_PERSISTENCE_DRIVER or "dynamodb").strip().lower()
        table_name = (settings.HEAR_DDB_TABLE or "").strip()
        if driver == "memory":
            return MemoryPersistenceAdapter()
        if driver != "dynamodb":
            Application.logger.warning(
                "Unknown persistence driver %r; selecting from environment", driver
            )
        if table_name:
            return DynamoUserSupport.build_dynamo_adapter(
                table_name=table_name,
                partition_key_name=settings.HEAR_DDB_PARTITION_KEY,
            )
        if settings.STAGE in ("staging", "production"):
            raise RuntimeError("HEAR_DDB_TABLE is required in staging/production")
        Application.logger.warning("HEAR_DDB_TABLE is unset; using non-durable memory persistence")
        return MemoryPersistenceAdapter()

    @staticmethod
    def build_skill(
        persistence_adapter=None, *, deps: ApplicationContainer | None = None
    ) -> AsyncSkill:
        """Create a fully configured skill application."""
        skill = AsyncSkill(
            persistence_adapter=persistence_adapter
            if persistence_adapter is not None
            else Application.build_persistence_adapter()
        )
        dependencies = deps or ApplicationContainer()
        RouteRegistry.register(skill, dependencies)
        return skill
