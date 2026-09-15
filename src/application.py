from __future__ import annotations

from config import settings
from src.alexa.runtime import AsyncSkill
from src.container import ApplicationContainer
from src.database.dynamo_user import DynamoUserSupport
from src.database.persistence import MemoryPersistenceAdapter
from src.registry import RouteRegistry
from src.services.logging_control import ApplicationLog


class Application:
    logger = ApplicationLog

    @staticmethod
    def build_persistence_adapter():
        driver = (settings.HEAR_PERSISTENCE_DRIVER or "dynamodb").strip().lower()
        table_name = (settings.HEAR_DDB_TABLE or "").strip()
        deployed = (
            str(settings.STAGE).strip().lower() in {"staging", "production"} or settings.is_lambda
        )
        if driver not in {"memory", "dynamodb"}:
            raise ValueError(f"Unsupported persistence driver: {driver}")
        if deployed and (driver == "memory" or not table_name):
            raise RuntimeError("A durable DynamoDB table is required in deployed environments")
        if driver == "memory":
            return MemoryPersistenceAdapter()
        if table_name:
            return DynamoUserSupport.build_dynamo_adapter(
                table_name=table_name,
                partition_key_name=settings.HEAR_DDB_PARTITION_KEY,
            )
        Application.logger.warning("HEAR_DDB_TABLE is unset; using non-durable memory persistence")
        return MemoryPersistenceAdapter()

    @staticmethod
    def build_skill(
        persistence_adapter=None, *, deps: ApplicationContainer | None = None
    ) -> AsyncSkill:
        """Create a fully configured skill application."""
        ApplicationLog.configure(settings.HEAR_LOGGING_ENABLED)
        skill = AsyncSkill(
            persistence_adapter=persistence_adapter
            if persistence_adapter is not None
            else Application.build_persistence_adapter()
        )
        dependencies = deps or ApplicationContainer()
        RouteRegistry.register(skill, dependencies)
        return skill
