from unittest.mock import AsyncMock

import pytest

from src.alexa.resolver_runner import ResolverWorkflowRunner
from src.alexa.search_speech import SearchSpeech
from src.application import Application
from src.clients.hear import HearApiClient
from src.clients.resolver import ResolverClient
from src.container import ApplicationContainer
from src.database.persistence import MemoryPersistenceAdapter
from src.models.resolver import ResolverResult
from src.utils.search_payload import SearchPayload
from tests.test_audio_player_runtime import USER_ID, _event

TAG_ID = "2f6c0d8e-9a1b-4c3d-8e7f-0a1b2c3d4e5f"


def _tag_result(utterance: str) -> ResolverResult:
    start = utterance.casefold().find("cancer support")
    entities = (
        [
            {
                "entityType": "tag",
                "entityId": TAG_ID,
                "canonicalValue": "Cancer Support",
                "originalText": "cancer support",
                "confidence": 98,
                "method": "exact",
                "start": start,
                "end": start + len("cancer support"),
            }
        ]
        if start >= 0
        else []
    )
    return ResolverResult.from_payload(
        {
            "status": "resolved",
            "intent": "tag" if entities else "search",
            "entities": entities,
            "slots": {
                "residualQuery": "",
                "latest": False,
                "isRecommended": False,
                "isPublication": False,
                "publishedFrom": None,
                "publishedTo": None,
            },
            "ambiguities": [],
            "timingMs": 2,
        }
    )


class TopicSession:
    def __init__(self, monkeypatch) -> None:
        self.searches: list[dict] = []
        self.resolved: list[str] = []

        async def resolve(_client, utterance, **_kwargs):
            self.resolved.append(utterance)
            return _tag_result(utterance)

        async def search(_client, payload, timeout_ms=None):
            del timeout_ms
            self.searches.append(payload)
            return {
                "results": [
                    {
                        "contentId": "cs-1",
                        "title": "Living with cancer",
                        "creatorId": "creator-1",
                        "creatorName": "Macmillan Voices",
                        "audioUrl": "https://cdn.hear.media/cs-1.mp3",
                        "durationMs": 300000,
                    }
                ],
                "total_hits": 1,
                "failed": False,
            }

        monkeypatch.setattr(ResolverClient, "resolve", resolve)
        monkeypatch.setattr(HearApiClient, "search", search)
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

    async def say(self, intent: str, dialog_state: str | None = None, **slots) -> dict:
        request = {
            "type": "IntentRequest",
            "intent": {
                "name": intent,
                "confirmationStatus": "NONE",
                "slots": {k: {"name": k, "value": v} for k, v in slots.items()},
            },
        }
        if dialog_state:
            request["dialogState"] = dialog_state
        skill = Application.build_skill(self.persistence, container=ApplicationContainer())
        return (await skill.invoke(_event(request), None))["response"]


def _speech(response: dict) -> str:
    return (response.get("outputSpeech") or {}).get("ssml", "")


@pytest.mark.asyncio
async def test_a_topic_tag_request_is_handled_instead_of_falling_back(monkeypatch):
    session = TopicSession(monkeypatch)

    response = await session.say(
        "OpenDiscoveryIntent", "IN_PROGRESS", searchQuery="play content on cancer support"
    )

    assert "didn't catch that" not in _speech(response)
    assert "content on Cancer Support" in _speech(response)


@pytest.mark.asyncio
async def test_find_me_something_on_a_topic_searches_that_topic(monkeypatch):
    session = TopicSession(monkeypatch)

    question = await session.say(
        "OpenDiscoveryIntent", searchQuery="find me something on cancer support"
    )
    playing = await session.say("AMAZON.YesIntent")

    assert session.resolved == ["play cancer support"]
    assert "content on Cancer Support" in _speech(question)
    assert session.searches[-1]["filter"] == {"tags": [TAG_ID]}
    assert "Playing content on Cancer Support." in _speech(playing)
    assert TAG_ID.split("-")[0] not in _speech(playing)


@pytest.mark.parametrize(
    ("spoken", "topic"),
    [
        ("on cancer support", "cancer support"),
        ("about gardening", "gardening"),
        ("good", None),
        ("for me", None),
        (None, None),
    ],
)
def test_recommendation_topic_strips_the_preposition(spoken, topic):
    assert ResolverWorkflowRunner._recommendation_topic(spoken) == topic


def test_spoken_labels_use_tag_names_not_ids():
    slots = {"tags": [TAG_ID], "tagNames": ["Cancer Support"], "residualQuery": ""}

    assert SearchPayload.resolved_request_label(slots) == "Cancer Support"
    assert SearchPayload.request_label(slots, "") == "Cancer Support"
    relation, subject = SearchSpeech._broad_result_context(
        {"query": "", "filter": {"tags": [TAG_ID]}}, "content on Cancer Support"
    )
    assert subject == "Cancer Support"
