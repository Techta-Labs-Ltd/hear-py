from __future__ import annotations

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor

from src.models.resolver_workflow import ResolverWorkflowRunner


class ResolverInterceptor(AbstractRequestInterceptor):
    def __init__(self, *, deps: object | None = None):
        self._workflow = ResolverWorkflowRunner(deps=deps)

    async def process(self, handler_input) -> None:
        await self._workflow.apply(handler_input)
