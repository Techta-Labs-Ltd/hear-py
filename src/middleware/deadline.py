from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor
from ask_sdk_core.handler_input import HandlerInput

from src.alexa.request import AlexaRequest
from src.utils.deadline import DeadlineBudget


class DeadlineModule:
    logger = logging.getLogger(__name__)


class LambdaDeadlineInterceptor(AbstractRequestInterceptor):
    """Logs Lambda timeout budget at the start of each request."""

    async def process(self, handler_input: HandlerInput):
        remaining_ms = DeadlineBudget.get_lambda_remaining_ms(handler_input)
        has_lambda_context = hasattr(handler_input, "context") and callable(
            getattr(handler_input.context, "get_remaining_time_in_millis", None)
        )
        DeadlineModule.logger.info(
            "Hear: request budget requestType=%s remainingMs=%s hasLambdaContext=%s",
            AlexaRequest.get_request_type(handler_input),
            remaining_ms,
            has_lambda_context,
        )
        if isinstance(remaining_ms, (int, float)) and remaining_ms > 0 and (remaining_ms < 6000):
            DeadlineModule.logger.warning(
                "Hear: Lambda timeout is below 8s; search may fail. Set function timeout to 8 seconds. remainingMs=%s",
                remaining_ms,
            )
