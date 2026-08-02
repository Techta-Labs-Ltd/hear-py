from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from config import settings
from src.resolver.normalize import normalize_utterance

logger = logging.getLogger(__name__)


def enable_offline_dependency_mode() -> None:
    """Prevent Semantic Router's optional LiteLLM dependency from using HTTP."""
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

ALEXA_SEMANTIC_ROUTES = {
    "PlayContentIntent": "general",
    "PlayLocalIntent": "local",
    "PlayRecommendationIntent": "trending",
    "ShowMoreBrowseIntent": "show_more",
    "PlayByOrganizationIntent": "organization",
    "PlayByCreatorIntent": "creator",
    "PlayPublicationIntent": "publication",
    "BrowseContentIntent": "browse",
    "WhatsTrendingIntent": "trending",
    "FeedbackEnjoyedIntent": "feedback_enjoyed",
    "FeedbackSomewhatIntent": "feedback_somewhat",
    "FeedbackNotEnjoyedIntent": "feedback_not_enjoyed",
    "SkipFeedbackIntent": "feedback_skip",
}

SEARCH_ROUTE_NAMES = frozenset({
    "browse", "creator", "general", "local", "organization", "publication", "trending",
})

ONBOARDING_ROUTE_SKIP = "onboarding_skip"
ONBOARDING_ROUTE_TOWN = "town_answer"

ONBOARDING_ROUTE_NAMES = frozenset({
    *SEARCH_ROUTE_NAMES, ONBOARDING_ROUTE_SKIP, ONBOARDING_ROUTE_TOWN,
})

ROUTE_SEEDS = {
    "general": (
        "play something about football",
        "find an article about accessibility",
        "play the latest news",
    ),
    "local": (
        "play news near me",
        "what is happening around my area",
        "find local recordings",
    ),
    "creator": (
        "play something by a creator",
        "find recordings from this author",
        "play content made by someone",
    ),
    "organization": (
        "play recordings from a talking newspaper",
        "find content from an organisation",
        "play something published by this group",
    ),
    "publication": (
        "play a publication",
        "play the latest publication from a creator",
        "find publications from an organisation",
    ),
    "trending": (
        "what is popular right now",
        "play what everyone is listening to",
        "recommend something for me",
    ),
    "browse": (
        "show me what is available",
        "let me browse the catalogue",
        "let us explore whatever is available",
        "what content do you have",
    ),
    "town_answer": (
        "I am in london",
        "my town is manchester",
        "I live in birmingham",
        "the city is leeds",
        "bristol",
        "swindon",
    ),
    "onboarding_skip": (
        "skip this question",
        "I do not want to say",
        "skip the location question",
        "do not ask about my town",
        "move on",
        "skip it",
    ),
}


@dataclass(frozen=True)
class SemanticDecision:
    route: str
    score: float


def _sample_text(sample: str) -> str:
    text = re.sub(r"\{[^{}]+\}", "something", sample)
    return normalize_utterance(text)


def load_route_utterances(model_path: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Load and group Alexa samples under internal semantic route names."""
    path = model_path or Path(__file__).parents[2] / "en-GB.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    intents = payload["interactionModel"]["languageModel"]["intents"]
    grouped: dict[str, list[str]] = {
        route: list(seeds) for route, seeds in ROUTE_SEEDS.items()
    }
    for intent in intents:
        route = ALEXA_SEMANTIC_ROUTES.get(str(intent.get("name") or ""))
        if not route:
            continue
        values = grouped.setdefault(route, [])
        values.extend(
            value
            for value in (_sample_text(sample) for sample in intent.get("samples") or [])
            if value
        )
    return {
        route: tuple(dict.fromkeys(values))
        for route, values in grouped.items()
        if values
    }


class SemanticIntentRouter:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        backend: Any | None = None,
        model_path: Path | None = None,
    ):
        self.enabled = (
            settings.HEAR_SEMANTIC_ROUTER_ENABLED if enabled is None else enabled
        )
        self._backend = backend
        self._model_path = model_path
        self._lock = threading.Lock()
        self._initialization_attempted = backend is not None

    def _build_backend(self):
        return self._create_backend(use_cached_index=True)

    def _create_backend(self, *, use_cached_index: bool):
        enable_offline_dependency_mode()
        import numpy as np
        from semantic_router import Route
        from semantic_router.encoders import FastEmbedEncoder
        from semantic_router.index.local import LocalIndex
        from semantic_router.routers import SemanticRouter

        routes = [
            Route(name=name, utterances=list(utterances))
            for name, utterances in load_route_utterances(self._model_path).items()
        ]
        encoder = FastEmbedEncoder(
            name=settings.HEAR_SEMANTIC_ROUTER_MODEL,
            cache_dir=settings.HEAR_SEMANTIC_ROUTER_CACHE_DIR,
            threads=settings.HEAR_SEMANTIC_ROUTER_THREADS,
            score_threshold=settings.HEAR_SEMANTIC_ROUTER_THRESHOLD,
        )
        index_path = Path(settings.HEAR_SEMANTIC_ROUTER_INDEX_PATH)
        if use_cached_index and index_path.is_file():
            try:
                with np.load(index_path, allow_pickle=False) as cached:
                    vectors = cached["index"]
                    index = LocalIndex(
                        routes=cached["routes"],
                        utterances=cached["utterances"],
                        dimensions=int(vectors.shape[1]),
                        index=vectors,
                    )
                return SemanticRouter(
                    encoder=encoder,
                    routes=routes,
                    index=index,
                    auto_sync=None,
                )
            except (OSError, KeyError, TypeError, ValueError):
                logger.exception(
                    "Semantic Router index cache is invalid; rebuilding locally"
                )
        return SemanticRouter(encoder=encoder, routes=routes, auto_sync="local")

    def _get_backend(self):
        if not self.enabled:
            return None
        if self._backend is not None or self._initialization_attempted:
            return self._backend
        with self._lock:
            if self._backend is not None or self._initialization_attempted:
                return self._backend
            self._initialization_attempted = True
            try:
                self._backend = self._build_backend()
            except Exception:
                logger.exception("Semantic Router initialization failed; using deterministic NLP")
        return self._backend

    def route(
        self,
        utterance: str | None,
        allowed_routes: Iterable[str] | None = None,
    ) -> SemanticDecision | None:
        normalized = normalize_utterance(utterance)
        backend = self._get_backend()
        if not normalized or backend is None:
            return None
        allowed = set(allowed_routes or ())
        try:
            choice = backend(
                normalized,
                route_filter=sorted(allowed) if allowed else None,
            )
        except Exception:
            logger.exception("Semantic Router decision failed; using deterministic NLP")
            return None
        name = str(getattr(choice, "name", "") or "")
        score = float(getattr(choice, "similarity_score", 0.0) or 0.0)
        if (
            not name
            or (allowed and name not in allowed)
            or score < settings.HEAR_SEMANTIC_ROUTER_THRESHOLD
        ):
            return None
        return SemanticDecision(name, score)

    def warm(self) -> bool:
        """Initialize the offline backend during resolver Lambda startup."""
        return self._get_backend() is not None


semantic_intent_router = SemanticIntentRouter()


def write_semantic_index(path: Path | None = None) -> Path:
    """Build and persist the Aurelio local index for container cold starts."""
    enable_offline_dependency_mode()
    import numpy as np

    destination = path or Path(settings.HEAR_SEMANTIC_ROUTER_INDEX_PATH)
    destination.parent.mkdir(parents=True, exist_ok=True)
    backend = SemanticIntentRouter(enabled=True)._create_backend(
        use_cached_index=False,
    )
    np.savez_compressed(
        destination,
        routes=backend.index.routes,
        utterances=backend.index.utterances,
        index=backend.index.index,
    )
    return destination
