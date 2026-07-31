from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.handlers.registry import REQUEST_HANDLERS
from src.nlp.classifier import classify_utterance
from src.nlp.patterns import ALEXA_TO_NLP
from src.resolver.engine import Resolver
from src.resolver.payload import build_hear_payload
from src.resolver.taxonomy import TaxonomyManager

ROOT = Path(__file__).parents[1]
MODEL_PATH = ROOT / "en-GB.json"
FIXTURES = Path(__file__).parent / "fixtures" / "taxonomy"
REPORT_PATH = Path(__file__).parent / "search_simulation_report.md"

TOPICS = ["news", "sport", "politics", "technology", "business", "health"]
FORMATS = ["podcast", "newspaper"]
TOWNS = ["Swindon", "Manchester", "London", "Burnley"]
CITIES = ["London", "Bristol"]
SELECTIONS = ["Walsall", "Wakefield", "Warrington", "Sussex Coast"]
CREATOR = "Adeshina Ayomide"
ORGANIZATION = "Andover Talking Newspaper"

LATEST_CARRIERS = {
    "play the latest {topic}",
    "play me the latest {topic}",
    "play me the newest {topic}",
    "play the newest {topic}",
    "play me recent {topic}",
    "play recent {topic}",
    "play me latest {topic}",
    "play latest {topic}",
    "get me the latest {topic}",
}

CATEGORY_CARRIERS = LATEST_CARRIERS | {
    "play {topic}",
    "play me {topic}",
    "find me {topic}",
    "play some {topic}",
    "give me {topic}",
    "play me some {topic}",
    "give me some {topic}",
    "put on some {topic}",
    "play me something on {topic}",
    "play me something about {topic}",
    "play something about {topic}",
    "find something about {topic}",
}

LOCAL_CARRIERS = {
    "play local",
    "play local content",
    "play near me",
    "play from my community",
    "play from my area",
    "play content near me",
    "find local content",
    "find content near me",
    "show me local content",
    "show me content near me",
    "what's local",
    "what's on near me",
    "what's happening near me",
    "local content",
    "nearby content",
    "content near me",
    "near me",
    "something near me",
    "nearby audio",
    "local audio",
    "local recordings",
    "play community",
    "play community content",
    "what's happening locally",
}

TOWN_CARRIERS = {
    "{townName}",
    "I am in {townName}",
    "I live in {townName}",
}

LOCATION_CARRIERS = {
    "{location}",
    "it's {location}",
    "I'm in {location}",
    "I live in {location}",
    "I'm from {location}",
    "set my location to {location}",
}

RECOMMEND_CARRIERS = {
    "recommend something",
    "what do you recommend",
    "recommend {recommendationQuery}",
}


def _model():
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def _intent_map():
    return {
        item["name"]: item
        for item in _model()["interactionModel"]["languageModel"]["intents"]
    }


@pytest.fixture(scope="module")
def resolver():
    manager = TaxonomyManager()
    manager.load_directory(FIXTURES)
    return Resolver(manager)


def _expand(samples: list[str], slot_values: dict[str, list[str]]):
    for sample in samples:
        filled = [sample]
        for slot_name, values in slot_values.items():
            marker = "{" + slot_name + "}"
            if marker not in sample:
                continue
            filled = [
                item.replace(marker, value)
                for item in filled
                for value in values
            ]
        yield from filled


def _plan_signature(plan) -> dict:
    return {
        "category": plan.category_slugs,
        "query": plan.query,
        "city": plan.city,
        "local": plan.is_local,
        "recommended": plan.is_recommended,
        "sort": plan.sort,
        "orgs": len(plan.organization_ids),
        "creators": len(plan.creator_ids),
        "ambiguous": len(plan.ambiguous_references),
        "unresolved": len(plan.unresolved_references),
    }


def _status(sig: dict) -> str:
    if sig["category"]:
        return "category"
    if sig["creators"]:
        return "creator"
    if sig["orgs"]:
        return "org"
    if sig["city"]:
        return "city"
    if sig["local"]:
        return "local"
    if sig["recommended"]:
        return "recommended"
    if sig["ambiguous"]:
        return "ambiguous"
    if sig["unresolved"]:
        return "unresolved"
    if sig["query"]:
        return "query"
    return "empty"


def _run_simulation(resolver: Resolver):
    intents = _intent_map()
    records = []

    def add(intent_name, sample, utterance, expectation=""):
        plan = resolver.resolve(utterance)
        sig = _plan_signature(plan)
        payload = build_hear_payload(plan)
        records.append({
            "intent": intent_name,
            "sample": sample,
            "utterance": utterance,
            "expected": expectation,
            "signature": sig,
            "status": _status(sig),
            "payload": payload,
        })

    for topic in TOPICS:
        for sample in CATEGORY_CARRIERS:
            add("PlayContentIntent", sample, sample.format(topic=topic),
                f"category {topic}")
    for fmt in FORMATS:
        for sample in ("play a {format}", "play the {format}",
                       "find me a {format}"):
            add("PlayContentIntent", sample, sample.format(format=fmt),
                "format")
    for sample in LOCAL_CARRIERS:
        add("PlayLocalIntent", sample, sample, "local")
    for town in TOWNS:
        for sample in ("play near {localQuery}", "play content near {localQuery}",
                       "find content near {localQuery}",
                       "show me content near {localQuery}",
                       "what's on near {localQuery}",
                       "what's happening near {localQuery}"):
            add("PlayLocalIntent", sample, sample.format(localQuery=town.lower()),
                "local")
    for topic in TOPICS[:2]:
        for sample in RECOMMEND_CARRIERS:
            add("PlayRecommendationIntent", sample,
                sample.format(recommendationQuery=topic), "recommended")
    for sample in ("play from the {organizationQuery}",
                   "play from {organizationQuery}",
                   "play content from {organizationQuery}",
                   "content from {organizationQuery}",
                   "show me content from {organizationQuery}",
                   "play from the {organizationQuery} organisation"):
        add("PlayByOrganizationIntent", sample,
            sample.format(organizationQuery=ORGANIZATION), "org")
    for sample in ("play from {creatorQuery}",
                   "play something by {creatorQuery}",
                   "play something from {creatorQuery}",
                   "play me {creatorQuery}",
                   "find {creatorQuery}",
                   "play latest recording from {creatorQuery}",
                   "play a recording from {creatorQuery}",
                   "latest from {creatorQuery}"):
        add("PlayByCreatorIntent", sample,
            sample.format(creatorQuery=CREATOR), "creator")
    for topic in TOPICS:
        for sample in ("what's the latest {topic}",
                       "what is the latest {topic}"):
            add("WhatsTrendingIntent", sample, sample.format(topic=topic),
                f"category {topic} + latest")
    for town in TOWNS:
        for sample in TOWN_CARRIERS:
            add("TownCaptureIntent", sample, sample.format(townName=town),
                "town")
    for city in CITIES:
        for sample in LOCATION_CARRIERS:
            add("SetLocationIntent", sample, sample.format(location=city),
                "city")
    for selection in SELECTIONS:
        for sample in ("{selection}", "I meant {selection}",
                       "the {selection} one"):
            add("ClarifySelectionIntent", sample,
                sample.format(selection=selection), "clarify")
    for sample in ("what's on", "what's available", "what's new",
                   "what have you got", "what's been published"):
        add("BrowseContentIntent", sample, sample, "browse")
    for sample in ("show me more", "what are the next ones", "keep going"):
        add("ShowMoreBrowseIntent", sample, sample, "show_more")
    return records


def test_all_search_intents_have_a_registered_owner():
    intents = _intent_map()
    handler_names = {cls.__name__ for cls in REQUEST_HANDLERS}
    for name in intents:
        if name.startswith("AMAZON."):
            continue
        owned = (
            f"{name}Handler" in handler_names
            or f"{name.removesuffix('Intent')}Handler" in handler_names
            or name in ALEXA_TO_NLP
        )
        assert owned, f"{name} has no handler and no NLP routing"


def test_every_simulated_utterance_resolves_without_error(resolver):
    records = _run_simulation(resolver)
    assert len(records) >= 250
    for record in records:
        sig = record["signature"]
        payload = record["payload"]
        assert set(payload) >= {"isLocal", "isRecommended", "query", "sort"}


def test_category_carriers_preserve_the_topic(resolver):
    records = _run_simulation(resolver)
    for record in records:
        if record["intent"] != "PlayContentIntent":
            continue
        if not record["expected"].startswith("category"):
            continue
        topic = record["utterance"].rsplit(" ", 1)[-1]
        assert record["signature"]["category"] == [topic], record["utterance"]


def test_latest_carriers_request_latest_sort(resolver):
    records = _run_simulation(resolver)
    latest_samples = {s for s in LATEST_CARRIERS}
    latest_samples |= {"what's the latest {topic}", "what is the latest {topic}"}
    for record in records:
        if record["sample"] in latest_samples:
            assert record["signature"]["sort"] == "latest", record["utterance"]


def test_local_carriers_are_local(resolver):
    records = _run_simulation(resolver)
    for record in records:
        if record["intent"] != "PlayLocalIntent":
            continue
        if record["sample"] in LOCAL_CARRIERS:
            assert record["signature"]["local"] is True, record["utterance"]


def test_near_query_carriers_capture_the_town(resolver):
    records = _run_simulation(resolver)
    for record in records:
        if record["intent"] != "PlayLocalIntent":
            continue
        if "{localQuery}" not in record["sample"]:
            continue
        town = record["utterance"].split()[-1].title()
        assert (
            record["signature"]["city"] == town
            or record["signature"]["local"] is True
        ), record["utterance"]


def test_recommendation_carriers_are_recommended(resolver):
    records = _run_simulation(resolver)
    for record in records:
        if record["sample"] in RECOMMEND_CARRIERS:
            assert record["signature"]["recommended"] is True, record["utterance"]


def test_organization_carriers_resolve_the_talking_newspaper(resolver):
    records = _run_simulation(resolver)
    for record in records:
        if record["intent"] != "PlayByOrganizationIntent":
            continue
        assert record["signature"]["orgs"] >= 1, record["utterance"]


def test_creator_carriers_resolve_the_creator(resolver):
    records = _run_simulation(resolver)
    for record in records:
        if record["intent"] != "PlayByCreatorIntent":
            continue
        assert record["signature"]["creators"] >= 1, record["utterance"]


def test_trending_carriers_preserve_topic_and_latest(resolver):
    records = _run_simulation(resolver)
    for record in records:
        if record["intent"] != "WhatsTrendingIntent":
            continue
        topic = record["utterance"].split()[-1]
        sig = record["signature"]
        assert sig["category"] == [topic], record["utterance"]
        assert sig["sort"] == "latest", record["utterance"]


def test_town_capture_resolves_the_town(resolver):
    records = _run_simulation(resolver)
    for record in records:
        if record["intent"] != "TownCaptureIntent":
            continue
        town = record["utterance"].split()[-1].title()
        sig = record["signature"]
        assert (
            sig["city"] == town
            or sig["local"] is True
            or sig["orgs"] >= 1
        ), record["utterance"]


def test_set_location_resolves_the_city(resolver):
    records = _run_simulation(resolver)
    for record in records:
        if record["intent"] != "SetLocationIntent":
            continue
        city = record["utterance"].split()[-1].title()
        assert record["signature"]["city"] == city, record["utterance"]


def test_clarification_selection_never_crashes_and_resolves_something(resolver):
    records = _run_simulation(resolver)
    for record in records:
        if record["intent"] != "ClarifySelectionIntent":
            continue
        sig = record["signature"]
        assert (
            sig["orgs"]
            or sig["city"]
            or sig["category"]
            or sig["ambiguous"]
            or sig["query"]
        ), record["utterance"]


def test_nlp_classifier_routes_hint_utterances(resolver):
    for utterance, expected in (
        ("what's trending", "trending"),
        ("what is trending", "trending"),
        ("show me more", "show_more"),
        ("keep going", "show_more"),
        ("what's on", "browse"),
        ("recommend something", "browse"),
    ):
        assert classify_utterance(utterance)["intent"] == expected, utterance


def test_scripted_user_journey(resolver):
    journey = [
        ("play me the latest sport", "category", "sport", "latest", False),
        ("play local news", "category", "news", "relevance", True),
        ("play politics", "category", "politics", "relevance", False),
        ("play from Andover Talking Newspaper", "org", None, "relevance", False),
        ("play from Adeshina Ayomide", "creator", None, "relevance", False),
    ]
    for utterance, kind, value, sort, local in journey:
        sig = _plan_signature(resolver.resolve(utterance))
        assert sig["sort"] == sort, utterance
        assert sig["local"] is local, utterance
        if kind == "category":
            assert sig["category"] == [value], utterance
        elif kind == "org":
            assert sig["orgs"] >= 1, utterance
        elif kind == "creator":
            assert sig["creators"] >= 1, utterance
    assert classify_utterance("what's trending")["intent"] == "trending"


def test_simulation_report_is_written(resolver):
    records = _run_simulation(resolver)
    lines = [
        "# Hear content-search simulation report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Corpus: {len(records)} simulated utterances from `en-GB.json`",
        f"Fixture taxonomy: `{FIXTURES.relative_to(ROOT)}`",
        "",
        "## Status counts",
        "",
        "| Status | Count |",
        "| --- | --- |",
    ]
    counts = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    for status, count in sorted(counts.items()):
        lines.append(f"| {status} | {count} |")
    lines += [
        "",
        "## By intent",
        "",
        "| Intent | Utterances | Statuses |",
        "| --- | --- | --- |",
    ]
    by_intent = {}
    for record in records:
        by_intent.setdefault(record["intent"], []).append(record)
    for intent, items in by_intent.items():
        statuses = sorted({record["status"] for record in items})
        lines.append(f"| {intent} | {len(items)} | {', '.join(statuses)} |")
    lines += [
        "",
        "## Sample resolutions",
        "",
        "| Intent | Utterance | Category | Query | City | Local | Recommended | Sort | Orgs | Creators |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in records[:120]:
        sig = record["signature"]
        lines.append(
            "| {intent} | {utterance} | {cat} | {query} | {city} | {local} | "
            "{rec} | {sort} | {orgs} | {creators} |".format(
                intent=record["intent"],
                utterance=record["utterance"].replace("|", "/"),
                cat=",".join(sig["category"]) or "-",
                query=sig["query"] or "-",
                city=sig["city"] or "-",
                local=sig["local"],
                rec=sig["recommended"],
                sort=sig["sort"],
                orgs=sig["orgs"],
                creators=sig["creators"],
            )
        )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    assert REPORT_PATH.exists()
