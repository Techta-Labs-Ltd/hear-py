from __future__ import annotations

import inspect
import logging
from typing import Any
from urllib.parse import urlparse

from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit

from config import settings


class AlexaMetrics:
    provider = Metrics(
        namespace=settings.HEAR_METRICS_NAMESPACE,
        service=settings.POWERTOOLS_SERVICE_NAME,
    )

    @staticmethod
    def increment(name: str) -> None:
        AlexaMetrics.provider.add_metric(name=name, unit=MetricUnit.Count, value=1)


class AlexaRuntime:
    logger = logging.getLogger(__name__)

    @staticmethod
    def _valid_card_image_url(value: Any) -> bool:
        try:
            parsed = urlparse(str(value or ""))
            return parsed.scheme == "https" and parsed.path.lower().endswith(
                (".jpg", ".jpeg", ".png")
            )
        except Exception:
            return False

    @staticmethod
    def _wrap(value: Any) -> Any:
        if isinstance(value, AttrDict):
            return value
        if isinstance(value, dict):
            return AttrDict(value)
        if isinstance(value, list):
            return [AlexaRuntime._wrap(v) for v in value]
        return value

    @staticmethod
    async def _resolve(value: Any) -> Any:
        return await value if inspect.isawaitable(value) else value

    @staticmethod
    def _process_caller(interceptor: Any):
        raw = inspect.getattr_static(type(interceptor), "process", None)
        if isinstance(raw, staticmethod):
            func = raw.__func__
            return lambda hi: func(hi)
        func = getattr(interceptor, "process")
        params = list(inspect.signature(raw if callable(raw) else func).parameters)
        if params and params[0] == "self":
            return lambda hi: raw(interceptor, hi)
        return lambda hi: func(hi)


class AttrDict(dict):
    def __init__(self, data: dict | None = None):
        super().__init__()
        for k, v in (data or {}).items():
            super().__setitem__(k, AlexaRuntime._wrap(v))

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key: str, value: Any) -> None:
        super().__setitem__(key, AlexaRuntime._wrap(value))

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, AlexaRuntime._wrap(value))


class AttributesManager:
    def __init__(self, request_envelope: AttrDict, persistence_adapter: Any = None):
        self._envelope = request_envelope
        self._adapter = persistence_adapter
        session = request_envelope.get("session") or {}
        self._session_attributes: dict = dict(session.get("attributes") or {})
        self._request_attributes: dict = {}
        self._persistent: dict | None = None
        self._persistent_loaded = False

    @property
    def request_attributes(self) -> dict:
        return self._request_attributes

    @request_attributes.setter
    def request_attributes(self, value: dict) -> None:
        self._request_attributes = value if value is not None else {}

    def get_request_attributes(self) -> dict:
        return self._request_attributes

    def set_request_attributes(self, value: dict) -> None:
        self._request_attributes = value if value is not None else {}

    @property
    def session_attributes(self) -> dict:
        return self._session_attributes

    def get_session_attributes(self) -> dict:
        return self._session_attributes

    def set_session_attributes(self, value: dict) -> None:
        self._session_attributes = value if value is not None else {}

    @property
    def persistent_attributes(self):
        return self._load_persistent()

    @persistent_attributes.setter
    def persistent_attributes(self, value: dict) -> None:
        self._persistent = value
        self._persistent_loaded = True

    async def _load_persistent(self) -> dict:
        if self._persistent_loaded:
            return self._persistent or {}
        if self._adapter is None:
            self._persistent = {}
        else:
            self._persistent = await self._adapter.get_attributes(self._envelope) or {}
        self._persistent_loaded = True
        return self._persistent

    async def save_persistent_attributes(self) -> None:
        if self._adapter is not None and self._persistent is not None:
            await self._adapter.save_attributes(self._envelope, self._persistent)


class ResponseBuilder:
    def __init__(self):
        self._response: dict = {}

    @staticmethod
    def _ssml(text: Any) -> str | None:
        if text is None:
            return None
        t = str(text)
        return t if t.lstrip().startswith("<speak") else f"<speak>{t}</speak>"

    def speak(self, text: Any) -> "ResponseBuilder":
        s = self._ssml(text)
        if s is not None:
            self._response["outputSpeech"] = {"type": "SSML", "ssml": s}
        return self

    def reprompt(self, text: Any) -> "ResponseBuilder":
        s = self._ssml(text)
        if s is not None:
            self._response["reprompt"] = {"outputSpeech": {"type": "SSML", "ssml": s}}
        return self

    def set_should_end_session(self, value: bool) -> "ResponseBuilder":
        self._response["shouldEndSession"] = bool(value)
        return self

    def with_should_end_session(self, value: bool) -> "ResponseBuilder":
        return self.set_should_end_session(value)

    def with_ask_for_permissions_consent_card(self, permissions) -> "ResponseBuilder":
        self._response["card"] = {
            "type": "AskForPermissionsConsent",
            "permissions": list(permissions or []),
        }
        return self

    def with_simple_card(self, title: Any, content: Any) -> "ResponseBuilder":
        self._response["card"] = {
            "type": "Simple",
            "title": str(title or "").strip(),
            "content": str(content or "").strip(),
        }
        return self

    def with_standard_card(
        self,
        title: Any,
        text: Any,
        *,
        small_image_url: str | None = None,
        large_image_url: str | None = None,
    ) -> "ResponseBuilder":
        card = {
            "type": "Standard",
            "title": str(title or "").strip(),
            "text": str(text or "").strip(),
        }
        image = {}
        if AlexaRuntime._valid_card_image_url(small_image_url):
            image["smallImageUrl"] = str(small_image_url)
        if AlexaRuntime._valid_card_image_url(large_image_url):
            image["largeImageUrl"] = str(large_image_url)
        if image:
            card["image"] = image
        self._response["card"] = card
        return self

    def add_directive(self, directive: Any) -> "ResponseBuilder":
        if directive:
            self._response.setdefault("directives", []).append(
                dict(directive) if isinstance(directive, dict) else directive
            )
        return self

    @property
    def response(self) -> dict:
        return self._response

    def get_response(self) -> dict:
        return self._response


class HandlerInput:
    def __init__(self, request_envelope, attributes_manager, context, response_builder):
        self.request_envelope = request_envelope
        self.attributes_manager = attributes_manager
        self.context = context
        self.response_builder = response_builder
        self._redispatch = None

    async def redispatch(self):
        if self._redispatch is None:
            return self.response_builder.response
        return await self._redispatch(self)


class AsyncSkill:
    def __init__(self, persistence_adapter: Any = None):
        self.persistence_adapter = persistence_adapter
        self.request_handlers: list = []
        self.exception_handlers: list = []
        self._request_interceptors: list = []
        self._response_interceptors: list = []

    def add_request_handler(self, handler: Any) -> None:
        self.request_handlers.append(handler)

    def add_exception_handler(self, handler: Any) -> None:
        self.exception_handlers.append(handler)

    def add_global_request_interceptor(self, interceptor: Any) -> None:
        self._request_interceptors.append(AlexaRuntime._process_caller(interceptor))

    def add_global_response_interceptor(self, interceptor: Any) -> None:
        self._response_interceptors.append(AlexaRuntime._process_caller(interceptor))

    async def invoke(self, event: dict, context: Any) -> dict:
        envelope = AttrDict(event)
        attrs = AttributesManager(envelope, self.persistence_adapter)
        handler_input = HandlerInput(envelope, attrs, context, ResponseBuilder())
        handler_input._redispatch = self._dispatch
        response: Any = None
        try:
            for caller in self._request_interceptors:
                await AlexaRuntime._resolve(caller(handler_input))
            response = await self._dispatch(handler_input)
        except Exception as exc:
            response = await self._dispatch_exception(handler_input, exc)
        for caller in self._response_interceptors:
            try:
                await AlexaRuntime._resolve(caller(handler_input))
            except Exception as exc:
                AlexaMetrics.increment("ResponseInterceptorFailure")
                AlexaRuntime.logger.exception(
                    "Alexa response interceptor failed interceptor=%s error=%s",
                    getattr(caller, "__qualname__", type(caller).__name__),
                    type(exc).__name__,
                )
        return self._build_envelope(handler_input, response)

    async def _dispatch(self, handler_input: HandlerInput) -> Any:
        for handler in self.request_handlers:
            try:
                can = await AlexaRuntime._resolve(handler.can_handle(handler_input))
            except Exception as exc:
                AlexaMetrics.increment("HandlerMatchFailure")
                AlexaRuntime.logger.warning(
                    "Alexa handler match failed handler=%s error=%s",
                    type(handler).__name__,
                    type(exc).__name__,
                )
                can = False
            if can:
                return await AlexaRuntime._resolve(handler.handle(handler_input))
        return handler_input.response_builder.response

    async def _dispatch_exception(self, handler_input: HandlerInput, exc: Exception) -> Any:
        for handler in self.exception_handlers:
            try:
                can = await AlexaRuntime._resolve(handler.can_handle(handler_input, exc))
            except Exception as match_error:
                AlexaMetrics.increment("ExceptionHandlerMatchFailure")
                AlexaRuntime.logger.warning(
                    "Alexa exception handler match failed handler=%s error=%s",
                    type(handler).__name__,
                    type(match_error).__name__,
                )
                can = False
            if can:
                return await AlexaRuntime._resolve(handler.handle(handler_input, exc))
        raise exc

    @staticmethod
    def _build_envelope(handler_input: HandlerInput, response: Any) -> dict:
        if response is None:
            response = handler_input.response_builder.response
        if isinstance(response, dict) and "version" in response and ("response" in response):
            return response
        return {
            "version": "1.0",
            "sessionAttributes": handler_input.attributes_manager.get_session_attributes() or {},
            "response": response or {},
        }
