from __future__ import annotations

from src.nlp.patterns import COMMAND_DENY

GATED_INTENTS: set[str] = {
    "PlayContentIntent",
    "PlayByOrganizationIntent",
    "PlayByCreatorIntent",
    "AMAZON.FallbackIntent",
}

BLOCKED_SINGLE_WORD: set[str] = {
    "yes", "no", "yeah", "yep", "nope", "stop", "pause", "resume", "next",
    "previous", "repeat", "again", "help", "cancel", "home", "back", "more",
    "enjoyed", "skip", "like", "love", "dislike", "good", "bad", "okay", "ok",
}


def _is_blocked_single_word(raw: str) -> bool:
    """Check whether a single-word utterance is blocked from gRPC resolution."""
    trimmed = str(raw).strip().lower()
    if not trimmed or " " in trimmed:
        return False
    return trimmed in COMMAND_DENY or trimmed in BLOCKED_SINGLE_WORD


def is_gated_for_grpc(alexa_intent: str | None, raw_utterance: str | None) -> bool:
    """Check whether an utterance should be routed through gRPC resolution."""
    if not alexa_intent or alexa_intent not in GATED_INTENTS:
        return False
    raw = str(raw_utterance).strip() if raw_utterance is not None else ""
    if not raw:
        return False
    if _is_blocked_single_word(raw):
        return False
    return True
