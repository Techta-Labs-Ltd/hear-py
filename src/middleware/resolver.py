from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from src.alexa.request import AlexaRequest
from src.models.resolver_runner import ResolverWorkflowRunner
from src.models.user import User


class ResolverInterceptor(AbstractRequestInterceptor):
    def __init__(self, *, deps: object | None = None):
        self._deps = deps

    async def process(self, handler_input) -> None:
        alexa_user_id = AlexaRequest.get_user_id(handler_input)
        listener_id = User.snapshot(handler_input).get("listenerId")
        workflow = ResolverWorkflowRunner(
            alexa_user_id=alexa_user_id,
            listener_id=listener_id,
            deps=self._deps,
        )
        await workflow.apply(handler_input)
