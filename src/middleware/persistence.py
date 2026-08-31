from __future__ import annotations

import asyncio
import logging

from ask_sdk_core.dispatch_components import (
    AbstractRequestInterceptor,
    AbstractResponseInterceptor,
)

from src.alexa.request import AlexaRequest
from src.alexa.runtime import AlexaMetrics
from src.models.user import User
from src.utils.deadline import DeadlineBudget


class PersistenceMiddlewareSupport:
    logger = logging.getLogger(__name__)


class LoadPersistenceInterceptor(AbstractRequestInterceptor):
    async def process(self, handler_input) -> None:
        request_type = AlexaRequest.get_request_type(handler_input)
        if request_type == "CanFulfillIntentRequest":
            User.hydrate_unavailable(handler_input)
            return
        remaining_ms = DeadlineBudget.get_lambda_remaining_ms(handler_input)
        if DeadlineBudget.should_skip_persistence_load(request_type, remaining_ms):
            User.hydrate_unavailable(handler_input)
            return
        reliable_load = DeadlineBudget.requires_reliable_persistence_load(request_type)
        budget_ms = 0 if reliable_load else DeadlineBudget.persistence_load_budget_ms(handler_input)
        stored: dict = {}
        try:
            if budget_ms > 0:
                try:
                    stored = (
                        await asyncio.wait_for(
                            User.read_persisted(handler_input),
                            timeout=budget_ms / 1000.0,
                        )
                        or {}
                    )
                except asyncio.TimeoutError:
                    User.hydrate_unavailable(handler_input)
                    AlexaMetrics.increment("PersistenceLoadTimeout")
                    PersistenceMiddlewareSupport.logger.warning(
                        "Hear: persistence load timed out degraded=true"
                    )
                    return
            else:
                stored = await User.read_persisted(handler_input)
        except Exception as exc:
            AlexaMetrics.increment("PersistenceLoadFailure")
            PersistenceMiddlewareSupport.logger.warning(
                "Hear: persistence load failed error=%s degraded=true",
                type(exc).__name__,
            )
            User.hydrate_unavailable(handler_input)
            return
        User.hydrate(handler_input, stored)


class SavePersistenceInterceptor(AbstractResponseInterceptor):
    async def process(self, handler_input) -> None:
        try:
            if not User.is_dirty(handler_input):
                return
            if not User.changed_fields(handler_input):
                return
            if not User.persistence_available(handler_input):
                AlexaMetrics.increment("PersistenceSaveSkipped")
                PersistenceMiddlewareSupport.logger.warning(
                    "Hear: persistence save skipped reason=load_unavailable degraded=true"
                )
                return
            reliable_save = User.requires_reliable_save(handler_input)
            budget_ms = (
                None if reliable_save else DeadlineBudget.persistence_save_budget_ms(handler_input)
            )
            snapshot = User.persisted_snapshot(User.snapshot(handler_input))
            if not reliable_save and budget_ms is not None and budget_ms < 200:
                return
            save_promise = User.write_persisted(handler_input, snapshot)
            if budget_ms is not None and not reliable_save:
                try:
                    await asyncio.wait_for(save_promise, timeout=budget_ms / 1000.0)
                except asyncio.TimeoutError:
                    AlexaMetrics.increment("PersistenceSaveTimeout")
                    PersistenceMiddlewareSupport.logger.warning(
                        "Hear: persistence save timed out degraded=true"
                    )
            else:
                await save_promise
        except Exception as exc:
            AlexaMetrics.increment("PersistenceSaveFailure")
            PersistenceMiddlewareSupport.logger.warning(
                "Hear: persistence save failed error=%s", type(exc).__name__
            )
