from __future__ import annotations

import logging

from src.nlp.grpc_reply_mapper import map_resolve_reply
from src.services.resolver_client import resolver_client

logger = logging.getLogger(__name__)


async def resolve(utterance: str | None, country_code: str | None = None) -> dict | None:
    """Resolve an utterance via gRPC and map the reply to NLP result format."""
    if not resolver_client.is_configured():
        return None

    raw = str(utterance).strip() if utterance is not None else ""
    if not raw:
        return None

    try:
        opts: dict = {}
        if country_code:
            opts["country_code"] = country_code
        reply = await resolver_client.resolve(raw, **opts)
        mapped = map_resolve_reply(reply)
        if mapped is not None:
            mapped["grpcResolved"] = True
        return mapped
    except Exception as err:
        code = getattr(err, "code", lambda: None)() if callable(getattr(err, "code", None)) else getattr(err, "code", None)
        details = getattr(err, "details", lambda: None)() if callable(getattr(err, "details", None)) else getattr(err, "details", None)
        logger.warning(
            "Hear: gRPC resolve failed — falling back to local NLP",
            extra={"error_code": code, "error_message": details or str(getattr(err, "message", err))},
        )
        return None
