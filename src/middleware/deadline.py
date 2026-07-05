from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor
from ask_sdk_core.handler_input import HandlerInput

from src.utils.skill_request import get_request_type
from src.utils.lambda_deadline import get_lambda_remaining_ms

logger = logging.getLogger(__name__)


class LambdaDeadlineInterceptor(AbstractRequestInterceptor):
    """Logs Lambda timeout budget at the start of each request."""

    async def process(self, handler_input: HandlerInput):
        remaining_ms = get_lambda_remaining_ms(handler_input)
        has_lambda_context = hasattr(handler_input, "context") \
            and callable(getattr(handler_input.context, "get_remaining_time_in_millis", None))

        logger.info(
            "Hear: request budget requestType=%s remainingMs=%s hasLambdaContext=%s",
            get_request_type(handler_input), remaining_ms, has_lambda_context,
        )

        if isinstance(remaining_ms, (int, float)) and remaining_ms > 0 and remaining_ms < 6000:
            logger.warning(
                "Hear: Lambda timeout is below 8s; search may fail. "
                "Set function timeout to 8 seconds. remainingMs=%s",
                remaining_ms,
            )
