import copy
from unittest.mock import AsyncMock

import pytest

from src.alexa.speech import Speech
from src.application import Application
from src.clients.hear import HearApiClient
from src.clients.resolver import ResolverClient
from src.container import ApplicationContainer
from src.database.persistence import MemoryPersistenceAdapter
from src.models.resolver import ResolverResult
from tests.test_audio_player_runtime import USER_ID, _event

PUBLICATION_ID = "c223ffec-341c-40df-a729-79531d45947b"
ENTITIES = {
    "tag": {
        "entityType": "tag",
        "entityId": "tree-planting",
        "canonicalValue": "#tree-planting",
        "originalText": "tree planting",
        "confidence": 100,
        "method": "bare_match",
        "start": 5,
        "end": 18,
    },
    "publication": {
        "entityType": "publication",
        "entityId": PUBLICATION_ID,
        "canonicalValue": "Tree Planting",
        "originalText": "tree planting",
        "confidence": 100,
        "method": "bare_match",
        "start": 5,
        "end": 18,
    },
    "category": {
        "entityType": "category",
        "entityId": "environment",
        "canonicalValue": "Environment",
        "originalText": "tree planting",
        "confidence": 100,
        "method": "bare_match",
        "start": 5,
        "end": 18,
    },
    "organization": {
        "entityType": "organization",
        "entityId": "org-york",
        "canonicalValue": "York Talking News",
        "originalText": "york talking news",
        "confidence": 100,
        "method": "exact",
        "start": 24,
        "end": 41,
    },
    "location": {
        "entityType": "location",
        "entityId": "york",
        "canonicalValue": "York",
        "originalText": "york",
        "confidence": 100,
        "method": "exact",
        "start": 24,
        "end": 28,
        "latitude": 53.96,
        "longitude": -1.08,
        "countryCode": "GB",
        "locationRole": "unspecified",
        "locationType": "city",
    },
}


def _result(*kinds: str) -> ResolverResult:
    return ResolverResult.from_payload(
        {
            "status": "resolved",
            "intent": "publication",
            "entities": [copy.deepcopy(ENTITIES[kind]) for kind in kinds],
            "slots": {
                "residualQuery": "",
                "latest": False,
                "isRecommended": False,
                "isPublication": True,
                "publishedFrom": None,
                "publishedTo": None,
            },
            "ambiguities": [],
            "timingMs": 1,
        }
    )


@pytest.mark.parametrize(
    ("kinds", "topic_filter"),
    [
        (("tag", "publication"), {"tags": ["tree-planting"]}),
        (("category", "publication"), {"categorySlugs": ["environment"]}),
        (
            ("category", "tag", "publication"),
            {"categorySlugs": ["environment"], "tags": ["tree-planting"]},
        ),
    ],
)
def test_publication_on_the_same_words_as_a_topic_is_offered_as_a_choice(kinds, topic_filter):
    payload = _result(*kinds).to_alexa_payload(original_utterance="play tree planting")

    assert payload["searchPayload"]["filter"] == topic_filter
    choice = payload["publicationChoice"]
    assert choice["name"] == "Tree Planting"
    assert choice["nlp"]["searchPayload"]["filter"] == {
        "publicationIds": [PUBLICATION_ID],
        "isPublication": True,
    }


@pytest.mark.parametrize("source", ["organization", "location"])
def test_organisation_or_location_keeps_the_normal_ranking(source):
    payload = _result("tag", "publication", source).to_alexa_payload(
        original_utterance="play tree planting"
    )

    assert "publicationChoice" not in payload


def test_publication_alone_is_unchanged():
    payload = _result("publication").to_alexa_payload(original_utterance="play tree planting")

    assert "publicationChoice" not in payload
    assert payload["searchPayload"]["filter"]["publicationIds"] == [PUBLICATION_ID]


class ChoiceSession:
    def __init__(self, monkeypatch, *kinds: str) -> None:
        self.searches: list[dict] = []

        async def resolve(_client, utterance, **_kwargs):
            return _result(*kinds)

        async def search(_client, payload, timeout_ms=None):
            del timeout_ms
            filters = dict(payload.get("filter") or {})
            self.searches.append(filters)
            publication = bool(filters.get("publicationIds"))
            return {
                "results": [
                    {
                        "contentId": "publication-track" if publication else "topic-item",
                        "title": "item",
                        "organizationId": "org-green",
                        "organizationName": "Green Voices",
                        "creatorId": "creator-green",
                        "creatorName": "Green Voices",
                        "audioUrl": "https://cdn.hear.media/item.mp3",
                        "durationMs": 300000,
                        **(
                            {
                                "publicationId": PUBLICATION_ID,
                                "publicationTitle": "Tree Planting",
                                "isPublication": True,
                            }
                            if publication
                            else {}
                        ),
                    }
                ],
                "total_hits": 1,
                "failed": False,
            }

        monkeypatch.setattr(ResolverClient, "resolve", resolve)
        monkeypatch.setattr(HearApiClient, "search", search)
        monkeypatch.setattr(HearApiClient, "availability", AsyncMock(return_value={"failed": True}))
        monkeypatch.setattr(
            HearApiClient,
            "resolve_listener_identity",
            AsyncMock(return_value={"listenerId": "listener-1"}),
        )
        monkeypatch.setattr("src.alexa.playback_workflow.Playback.emit", AsyncMock())
        self.persistence = MemoryPersistenceAdapter()
        self.persistence._store[USER_ID] = {
            "onboardingComplete": True,
            "listenerId": "listener-1",
            "playCount": 3,
        }

    async def say(self, intent: str, **slots) -> dict:
        request = {
            "type": "IntentRequest",
            "intent": {
                "name": intent,
                "confirmationStatus": "NONE",
                "slots": {k: {"name": k, "value": v} for k, v in slots.items()},
            },
        }
        skill = Application.build_skill(self.persistence, container=ApplicationContainer())
        return (await skill.invoke(_event(request), None))["response"]

    async def ask(self) -> str:
        return _speech(await self.say("SearchContentIntent", searchQuery="tree planting"))


def _speech(response: dict) -> str:
    return (response.get("outputSpeech") or {}).get("ssml", "")


def _played(response: dict) -> list[str]:
    return [
        directive["audioItem"]["stream"]["token"]
        for directive in response.get("directives") or []
        if directive.get("type") == "AudioPlayer.Play"
    ]


@pytest.mark.asyncio
async def test_yes_plays_the_publication(monkeypatch):
    session = ChoiceSession(monkeypatch, "tag", "publication")

    assert Speech.PUBLICATION_CHOICE("Tree Planting") in await session.ask()
    response = await session.say("AMAZON.YesIntent")

    assert _played(response) == ["publication-track"]
    assert session.searches[-1]["publicationIds"] == [PUBLICATION_ID]


@pytest.mark.asyncio
async def test_no_moves_to_the_normal_topic_confirmation(monkeypatch):
    session = ChoiceSession(monkeypatch, "category", "tag", "publication")
    await session.ask()

    question = _speech(await session.say("AMAZON.NoIntent"))
    response = await session.say("AMAZON.YesIntent")

    assert "Did you want me to play content on environment and tree planting?" in question
    assert _played(response) == ["topic-item"]
    assert session.searches[-1] == {"categorySlugs": ["environment"], "tags": ["tree-planting"]}


@pytest.mark.asyncio
async def test_no_then_no_declines_normally(monkeypatch):
    session = ChoiceSession(monkeypatch, "tag", "publication")
    await session.ask()
    await session.say("AMAZON.NoIntent")

    response = await session.say("AMAZON.NoIntent")

    assert _played(response) == []
    assert "What would you like" in _speech(response) or "Please say the name" in _speech(response)


@pytest.mark.asyncio
async def test_unclear_answer_is_asked_once_more_then_the_publication_plays(monkeypatch):
    session = ChoiceSession(monkeypatch, "tag", "publication")
    await session.ask()

    retry = _speech(await session.say("AMAZON.FallbackIntent"))
    response = await session.say("AMAZON.FallbackIntent")

    assert Speech.PUBLICATION_CHOICE_RETRY("Tree Planting") in retry
    assert _played(response) == ["publication-track"]
