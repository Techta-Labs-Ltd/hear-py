from __future__ import annotations

import asyncio
from src.services.logging_control import ApplicationLog

from ask_sdk_core.dispatch_components import (
    AbstractRequestInterceptor,
    AbstractResponseInterceptor,
)

from src.alexa.request import AlexaRequest
from src.alexa.runtime import AlexaMetrics
from src.models.listener import Listener
from src.models.user import CommitResult, CommitStatus, EssentialPersistenceError, User
from src.utils.deadline import DeadlineBudget


class PersistenceMiddlewareSupport:
    logger = ApplicationLog

    @staticmethod
    def apply_identity(handler_input) -> None:
        identity = Listener.identity(handler_input)
        store = User.snapshot(handler_input)
        updates = {}
        if identity and identity.listener_id:
            updates["listenerId"] = identity.listener_id
        if identity and identity.user_email and store.get("userEmail") != identity.user_email:
            updates["userEmail"] = identity.user_email
        if updates:
            User.update(handler_input, updates)

    @staticmethod
    def hydrate_unavailable(handler_input) -> None:
        User.hydrate_unavailable(handler_input)
        PersistenceMiddlewareSupport.apply_identity(handler_input)


class LoadPersistenceInterceptor(AbstractRequestInterceptor):
    async def process(self, handler_input) -> None:
        request_type = AlexaRequest.get_request_type(handler_input)
        if request_type == "CanFulfillIntentRequest":
            PersistenceMiddlewareSupport.hydrate_unavailable(handler_input)
            return
        remaining_ms = DeadlineBudget.get_lambda_remaining_ms(handler_input)
        if DeadlineBudget.should_skip_persistence_load(request_type, remaining_ms):
            PersistenceMiddlewareSupport.hydrate_unavailable(handler_input)
            return
        budget_ms = DeadlineBudget.persistence_load_budget_ms(handler_input)
        if budget_ms <= 0:
            PersistenceMiddlewareSupport.hydrate_unavailable(handler_input)
            return
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
                    PersistenceMiddlewareSupport.hydrate_unavailable(handler_input)
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
            PersistenceMiddlewareSupport.hydrate_unavailable(handler_input)
            return
        User.hydrate(handler_input, stored)
        used_alias = bool(
            getattr(
                handler_input.attributes_manager,
                "used_alias_persistence",
                False,
            )
        )
        PersistenceMiddlewareSupport.apply_identity(handler_input)
        if used_alias:
            AlexaMetrics.increment("PersistenceAliasCopied")


class SavePersistenceInterceptor(AbstractResponseInterceptor):
    async def process(self, handler_input) -> CommitResult:
        essential = User.requires_reliable_save(handler_input)
        if not User.is_dirty(handler_input) or not User.changed_fields(handler_input):
            return CommitResult(CommitStatus.UNCHANGED, essential)
        if not User.persistence_available(handler_input):
            return self._result(CommitStatus.UNAVAILABLE, essential)
        budget_ms = DeadlineBudget.persistence_save_budget_ms(handler_input)
        if budget_ms <= 0:
            return self._result(CommitStatus.DEADLINE_EXCEEDED, essential)
        try:
            snapshot = User.persisted_snapshot(User.snapshot(handler_input))
            await asyncio.wait_for(
                User.write_persisted(handler_input, snapshot), timeout=budget_ms / 1000.0
            )
        except asyncio.TimeoutError:
            return self._result(CommitStatus.DEADLINE_EXCEEDED, essential)
        except Exception as exc:
            AlexaMetrics.increment("PersistenceSaveFailure")
            PersistenceMiddlewareSupport.logger.warning(
                "Hear: persistence save failed error=%s", type(exc).__name__
            )
            return self._result(CommitStatus.FAILED, essential)
        return CommitResult(CommitStatus.SAVED, essential)

    @staticmethod
    def _result(status: CommitStatus, essential: bool) -> CommitResult:
        result = CommitResult(status, essential)
        AlexaMetrics.increment("PersistenceCommitFailure")
        PersistenceMiddlewareSupport.logger.warning(
            "Hear: persistence commit status=%s essential=%s", status, essential
        )
        if essential:
            raise EssentialPersistenceError(result)
        return result
