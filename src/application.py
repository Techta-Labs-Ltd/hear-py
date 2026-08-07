"""Application composition for the Hear Alexa skill."""
from __future__ import annotations

import logging

from config import settings
from src.adapters.dynamodb_persistence import build_dynamo_adapter
from src.adapters.memory_persistence import MemoryPersistenceAdapter
from src.registry import register_handlers

from src.middleware import register_middleware
from src.runtime import AsyncSkill

logger = logging.getLogger(__name__)


def build_persistence_adapter():
    """Build the configured persistence adapter with a safe local fallback."""
    driver = (settings.HEAR_PERSISTENCE_DRIVER or "dynamodb").strip().lower()
    table_name = (settings.HEAR_DDB_TABLE or "").strip()

    if driver == "memory":
        return MemoryPersistenceAdapter()
    if driver != "dynamodb":
        logger.warning("Unknown persistence driver %r; selecting from environment", driver)
    if table_name:
        return build_dynamo_adapter(table_name=table_name)
    if settings.STAGE in ("staging", "production"):
        raise RuntimeError("HEAR_DDB_TABLE is required in staging/production")
    logger.warning("HEAR_DDB_TABLE is unset; using non-durable memory persistence")
    return MemoryPersistenceAdapter()


def build_skill(persistence_adapter=None) -> AsyncSkill:
    """Create a fully configured skill application."""
    skill = AsyncSkill(
        persistence_adapter=persistence_adapter
        if persistence_adapter is not None
        else build_persistence_adapter()
    )
    register_middleware(skill)
    register_handlers(skill)
    return skill
