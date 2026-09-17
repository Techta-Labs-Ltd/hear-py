from __future__ import annotations

import pytest

from src.models.availability_request import AvailabilityRequest
from src.models.resolver import ResolverResult
from src.models.resolver_inputs import ResolverSlot
from src.models.resolver_workflow import ResolverWorkflow


def _entity(entity_type: str, name: str, utterance: str, *, start: int = 0, end: int | None = None) -> dict:
    return {
        "entityType": entity_type,
        "entityId": f"{entity_type}-1",
        "canonicalValue": name,
        "originalText": name,
        "confidence": 100,
        "method": "bare_match",
        "start": start,
        "end": len(name) if end is None else end,
        "latitude": None,
        "longitude": None,
        "countryCode": None,
        "locationRole": None,
    }


def _resolver_payload(entity_type: str, name: str, utterance: str, **entity_overrides) -> dict:
    entity = _entity(entity_type, name, utterance)
    entity.update(entity_overrides)
    return {
        "status": "resolved",
        "intent": entity_type,
        "entities": [entity],
        "slots": {
            "residualQuery": "",
            "publishedFrom": 1789599600,
            "publishedTo": 1789641496,
            "dateQuery": "today",
            "dateLabel": "today",
            "temporalOriginal": "today",
        },
        "ambiguities": [],
        "timingMs": 1,
    }


@pytest.mark.parametrize(
    ("entity_type", "source_name"),
    [
        ("organization", "Fareham Today"),
        ("creator", "Monday News"),
        ("publication", "May Talking News"),
        ("organization", "The Weekender"),
        ("publication", "Q1 Voice"),
        ("creator", "2025 Voice"),
        ("publication", "2025-05-12 News"),
    ],
)
def test_source_temporal_terms_do_not_create_date_filters(entity_type: str, source_name: str):
    result = ResolverResult.from_payload(
        _resolver_payload(entity_type, source_name, source_name)
    ).to_alexa_payload(original_utterance=source_name)

    source_key = f"{entity_type}Ids"
    assert result["searchPayload"]["filter"][source_key] == [f"{entity_type}-1"]
    assert not (set(result["slots"]) & {"publishedFrom", "publishedTo", "dateQuery", "dateLabel", "temporalOriginal"})
    assert not (
        set(result["slots"]["searchPlan"]["filter"])
        & {"publishedFrom", "publishedTo", "dateQuery", "dateLabel", "temporalOriginal"}
    )
    assert not (
        set(result["searchPayload"]["filter"])
        & {"publishedFrom", "publishedTo", "dateQuery", "dateLabel", "temporalOriginal"}
    )


@pytest.mark.parametrize(
    ("entity_type", "source_name", "utterance"),
    [
        ("organization", "Fareham Today", "Fareham Today today"),
        ("creator", "Monday News", "Monday News from last week"),
        ("publication", "May Talking News", "May Talking News in May 2025"),
        ("organization", "2025 Voice", "2025 Voice on 2025-05-12"),
    ],
)
def test_explicit_temporal_term_outside_source_keeps_date_filters(
    entity_type: str, source_name: str, utterance: str
):
    result = ResolverResult.from_payload(
        _resolver_payload(entity_type, source_name, utterance)
    ).to_alexa_payload(original_utterance=utterance)

    assert result["slots"]["publishedFrom"] == 1789599600
    assert result["slots"]["publishedTo"] == 1789641496
    assert result["searchPayload"]["filter"]["publishedFrom"] == 1789599600
    assert result["searchPayload"]["filter"]["publishedTo"] == 1789641496


def test_malformed_source_span_keeps_date_filters():
    source_name = "Fareham Today"
    result = ResolverResult.from_payload(
        _resolver_payload("organization", source_name, source_name, start=100, end=113)
    ).to_alexa_payload(original_utterance=source_name)

    assert result["slots"]["publishedFrom"] == 1789599600
    assert result["searchPayload"]["filter"]["publishedTo"] == 1789641496


def test_search_request_keeps_source_filter_without_an_invented_date_filter():
    source_name = "Fareham Today"
    result = ResolverResult.from_payload(
        _resolver_payload("organization", source_name, source_name)
    ).to_alexa_payload(original_utterance=source_name)

    outbound = AvailabilityRequest.local(
        result,
        alexa_user_id="alexa-user",
        user_state={"listenerId": "listener-1"},
    ).to_search_payload()

    assert outbound["filter"] == {"organizationIds": ["organization-1"]}
    assert outbound["alexaUserId"] == "alexa-user"
    assert outbound["listenerId"] == "listener-1"


def test_alexa_date_constraint_is_guarded_after_source_resolution():
    source_name = "Fareham Today"
    resolver_utterance = "play from Fareham Today"
    result = ResolverResult.from_payload(
        _resolver_payload(
            "organization",
            source_name,
            resolver_utterance,
            start=len("play from "),
            end=len(resolver_utterance),
        )
    ).to_alexa_payload(original_utterance=resolver_utterance)

    constrained = ResolverWorkflow.apply_alexa_constraints(
        result,
        "PlayContentIntent",
        {"dateQuery": ResolverSlot(resolved="2026-09-16", spoken="today")},
        resolver_utterance,
    )

    assert constrained["searchPayload"]["filter"]["organizationIds"] == ["organization-1"]
    assert "publishedFrom" not in constrained["slots"]
    assert "publishedTo" not in constrained["searchPayload"]["filter"]


def test_alexa_date_constraint_survives_when_outside_source_span():
    source_name = "Fareham Today"
    utterance = "Fareham Today today"
    result = ResolverResult.from_payload(
        _resolver_payload("organization", source_name, utterance)
    ).to_alexa_payload(original_utterance=utterance)

    constrained = ResolverWorkflow.apply_alexa_constraints(
        result,
        "PlayContentIntent",
        {"dateQuery": ResolverSlot(resolved="2026-09-16", spoken="today")},
        utterance,
    )

    assert constrained["searchPayload"]["filter"]["organizationIds"] == ["organization-1"]
    assert "publishedFrom" in constrained["slots"]
    assert "publishedTo" in constrained["searchPayload"]["filter"]
