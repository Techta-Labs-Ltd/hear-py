from __future__ import annotations
from ask_sdk_core.dispatch_components import AbstractRequestInterceptor
from src.utils.skill_request import get_request_type
from src.services.persistence import get_store


class LocalityGateMiddleware(AbstractRequestInterceptor):
    """Block 'local' intent requests when no locality data is available."""

    def process(self, handler_input) -> None:
        request_type = get_request_type(handler_input)
        if request_type != "IntentRequest":
            return

        attrs = handler_input.attributes_manager.request_attributes
        nlp = attrs.get("_nlp")
        if not nlp or not nlp.get("intent"):
            return

        if nlp["intent"] != "local":
            return

        store = get_store(handler_input)
        has_location = (
            store.get("locality")
            or store.get("userCity")
            or store.get("latitude")
            or store.get("devicePostalCode")
        )
        if has_location:
            return

        attrs["_localityGateBlocked"] = True
        handler_input.attributes_manager.request_attributes = attrs
