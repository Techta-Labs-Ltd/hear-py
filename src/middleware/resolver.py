from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from src.alexa.request import AlexaRequest
from src.alexa.resolver_runner import ResolverWorkflowRunner
from src.clients.progressive import ProgressiveResponseClient
from src.clients.resolver import ResolverClient
from src.models.user import User


class ResolverInterceptor(AbstractRequestInterceptor):
    def __init__(
        self,
        progressive: ProgressiveResponseClient,
        resolver: ResolverClient,
        user: User,
    ) -> None:
        self._progressive = progressive
        self._resolver = resolver
        self._user = user

    async def process(self, handler_input) -> None:
        alexa_user_id = AlexaRequest.get_user_id(handler_input)
        listener_id = User.snapshot(handler_input).get("listenerId")
        workflow = ResolverWorkflowRunner(
            alexa_user_id=alexa_user_id,
            listener_id=listener_id,
            progressive=self._progressive,
            resolver=self._resolver,
            user=self._user,
        )
        await workflow.apply(handler_input)
