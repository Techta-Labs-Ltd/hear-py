from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from src.nlp.classifier import classify_utterance
from src.resolver.search import Resolver
from src.resolver.alexa import alexa_resolver
from src.resolver.taxonomy import TaxonomyManager, TaxonomyRecord, TaxonomySnapshot
from src.services.semantic_routing import (
    SemanticIntentRouter,
    enable_offline_dependency_mode,
    load_route_utterances,
)


@dataclass
class Choice:
    name: str
    similarity_score: float


class FakeBackend:
    def __init__(self, name: str, score: float):
        self.name = name
        self.score = score
        self.calls = []

    def __call__(self, text, route_filter=None):
        self.calls.append((text, route_filter))
        return Choice(self.name, self.score)


def test_routes_are_sourced_from_the_alexa_model():
    routes = load_route_utterances(
        Path(__file__).parents[1] / "en-GB.json"
    )
    assert "play me the latest {topic}" not in routes["general"]
    assert "play me the latest something" in routes["general"]
    assert "what happening near me" in routes["local"]
    assert "i enjoyed it" in routes["feedback_enjoyed"]


def test_semantic_router_enforces_threshold_and_route_filter():
    accepted_backend = FakeBackend("local", 0.91)
    router = SemanticIntentRouter(enabled=True, backend=accepted_backend)
    decision = router.route("what is happening close to home", {"local", "general"})
    assert decision is not None
    assert decision.route == "local"
    assert accepted_backend.calls[0][1] == ["general", "local"]

    rejected = SemanticIntentRouter(
        enabled=True, backend=FakeBackend("local", 0.2),
    )
    assert rejected.route("anything") is None


def test_deterministic_entity_route_does_not_call_semantic_backend(monkeypatch):
    manager = TaxonomyManager()
    manager._snapshot = TaxonomySnapshot("test", [
        TaxonomyRecord("category", "sport", slug="sport"),
        TaxonomyRecord(
            "location", "Burnley",
            metadata={"city": "Burnley", "countryCode": "gb"},
        ),
    ])
    monkeypatch.setattr("src.resolver.alexa.resolver", Resolver(manager))
    backend = FakeBackend("organization", 0.99)
    monkeypatch.setattr(
        "src.resolver.alexa.semantic_intent_router",
        SemanticIntentRouter(enabled=True, backend=backend),
    )

    result = alexa_resolver.resolve("play sport in burnley")

    assert result["intent"] == "category"
    assert result["slots"]["category"] == "sport"
    assert result["slots"]["city"] == "Burnley"
    assert result["slots"]["semanticRoute"] is None
    assert backend.calls == []


def test_offline_dependency_mode_overrides_remote_litellm_setting(monkeypatch):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "False")
    enable_offline_dependency_mode()
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"


def test_semantic_route_handles_non_exact_control_language(monkeypatch):
    monkeypatch.setattr(
        "src.nlp.classifier.semantic_intent_router",
        SemanticIntentRouter(
            enabled=True, backend=FakeBackend("browse", 0.9),
        ),
    )
    result = classify_utterance("let us explore whatever is available")
    assert result["intent"] == "browse"
    assert result["semanticRoute"] == "browse"
    assert result["confidence"] == "high"


def test_publication_language_routes_deterministically_without_semantic_backend(
    monkeypatch,
):
    backend = FakeBackend("general", 0.99)
    monkeypatch.setattr(
        "src.nlp.classifier.semantic_intent_router",
        SemanticIntentRouter(enabled=True, backend=backend),
    )

    result = classify_utterance("play a publication")

    assert result["intent"] == "publication"
    assert result["slots"]["isPublication"] is True
    assert result["confidence"] == "high"
    assert backend.calls == []
