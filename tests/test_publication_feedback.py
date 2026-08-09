from __future__ import annotations

import pytest

from src.services.feedback import FeedbackService
from src.services.store import DEFAULT_STORE
from src.services.queue import init_queue
from src.handlers.feedback import FeedbackEnjoyedHandler
from src.runtime import AttrDict


def _state(index: int, *, listened=60_000, duration=60_000, count=13):
    return {
        "contentId": f"track-{index}",
        "publicationId": "publication-1",
        "publicationTitle": "The Weekly Edition",
        "trackIndex": index,
        "trackCount": count,
        "listenedMs": listened,
        "durationMs": duration,
        "queueId": "queue-1",
        "organizationId": "org-1",
        "organizationName": "York Talking News",
        "creatorId": "creator-1",
        "creatorName": "A Reader",
        "category": "news",
    }


def _store(mock_handler_input, **updates):
    mock_handler_input.attributes_manager.request_attributes["_store"] = {
        **DEFAULT_STORE,
        **updates,
    }


def test_six_of_thirteen_tracks_does_not_create_publication_feedback(mock_handler_input):
    _store(mock_handler_input)
    for index in range(6):
        FeedbackService.update_publication_progress(
            mock_handler_input, _state(index), completed=True,
        )

    candidate = FeedbackService.finalize_publication(
        mock_handler_input, "publication-1",
    )

    assert candidate is None
    assert mock_handler_input.attributes_manager.request_attributes["_store"]["feedbackCandidates"] == []
    assert "publication-1" in mock_handler_input.attributes_manager.request_attributes["_store"]["publicationFeedbackProgress"]


def test_below_threshold_progress_accumulates_after_publication_boundary(mock_handler_input):
    _store(mock_handler_input)
    for index in range(6):
        FeedbackService.update_publication_progress(
            mock_handler_input, _state(index), completed=True,
        )
    assert FeedbackService.finalize_publication(
        mock_handler_input, "publication-1",
    ) is None

    FeedbackService.update_publication_progress(
        mock_handler_input, _state(6), completed=True,
    )
    candidate = FeedbackService.finalize_publication(
        mock_handler_input, "publication-1",
    )

    assert candidate["meaningfulTrackCount"] == 7
    assert candidate["coverage"] >= 0.5


def test_seven_of_thirteen_tracks_creates_one_publication_candidate(mock_handler_input):
    _store(mock_handler_input)
    for index in range(7):
        FeedbackService.update_publication_progress(
            mock_handler_input, _state(index), completed=True,
        )

    candidate = FeedbackService.finalize_publication(
        mock_handler_input, "publication-1",
    )

    assert candidate["feedbackKey"] == "publication:publication-1"
    assert candidate["subjectType"] == "publication"
    assert candidate["meaningfulTrackCount"] == 7
    assert candidate["expectedTrackCount"] == 13
    assert candidate["title"] == "The Weekly Edition"


def test_duration_weighting_uses_total_publication_duration(mock_handler_input):
    _store(mock_handler_input, playbackQueue={
        "queueId": "queue-1",
        "publicationId": "publication-1",
        "publicationTrackCount": 2,
        "publicationTotalDurationMs": 400_000,
        "orderedContentIds": ["track-0", "track-1"],
        "currentIndex": 0,
    })
    FeedbackService.update_publication_progress(
        mock_handler_input,
        _state(0, listened=150_000, duration=300_000, count=2),
    )
    progress = FeedbackService.update_publication_progress(
        mock_handler_input,
        _state(1, listened=50_000, duration=100_000, count=2),
    )

    assert progress["coverage"] == 0.5
    assert FeedbackService.finalize_publication(
        mock_handler_input, "publication-1",
    ) is not None


def test_duplicate_and_out_of_order_progress_uses_maximum_per_track(mock_handler_input):
    _store(mock_handler_input)
    FeedbackService.update_publication_progress(
        mock_handler_input, _state(0, listened=50_000),
    )
    FeedbackService.update_publication_progress(
        mock_handler_input, _state(0, listened=10_000),
    )
    progress = FeedbackService.update_publication_progress(
        mock_handler_input, _state(0, listened=40_000),
    )

    assert progress["tracks"]["track-0"]["listenedMs"] == 50_000
    assert len(progress["tracks"]) == 1


def test_publication_track_never_creates_individual_candidate_mid_queue(mock_handler_input):
    _store(mock_handler_input, playbackQueue={
        "queueId": "queue-1",
        "publicationId": "publication-1",
        "publicationTrackCount": 13,
        "orderedContentIds": [f"track-{index}" for index in range(13)],
        "currentIndex": 0,
    })

    candidate = FeedbackService.record_candidate(
        mock_handler_input, _state(0), completed=True,
    )

    store = mock_handler_input.attributes_manager.request_attributes["_store"]
    assert candidate is None
    assert store["feedbackCandidates"] == []
    assert store["awaitingFeedback"] is False


def test_loaded_page_boundary_is_not_publication_end_when_more_pages_exist():
    state = {
        "contentId": "track-2",
        "publicationId": "publication-1",
    }
    store = {
        "playbackQueue": {
            "publicationId": "publication-1",
            "orderedContentIds": ["track-0", "track-1", "track-2"],
            "currentIndex": 2,
            "pagination": {
                "currentPage": 0,
                "totalPages": 4,
            },
        },
    }

    assert FeedbackService._publication_is_last_track(state, store) is False


def test_standalone_content_keeps_individual_feedback(mock_handler_input):
    _store(mock_handler_input)
    candidate = FeedbackService.record_candidate(mock_handler_input, {
        "contentId": "standalone-1",
        "title": "Standalone story",
        "creatorId": "creator-1",
        "creatorName": "Creator One",
        "listenedMs": 120_000,
        "sessionId": "session-1",
    }, completed=True)

    assert candidate["feedbackKey"] == "standalone-1"
    assert candidate.get("subjectType") is None


def test_publication_prompt_uses_publication_wording(mock_handler_input):
    _store(mock_handler_input, awaitingFeedback=True, pendingFeedback={
        "feedbackKey": "publication:publication-1",
        "subjectType": "publication",
        "publicationId": "publication-1",
        "title": "The Weekly Edition",
        "completed": True,
    })

    FeedbackService().pending_response(mock_handler_input)

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "You listened to The Weekly Edition" in spoken
    assert "Did you enjoy this publication" in spoken


def test_publication_queue_records_expected_count_and_duration(mock_handler_input):
    _store(mock_handler_input)
    queue = init_queue(mock_handler_input, [
        {
            "contentId": "track-0",
            "publicationId": "publication-1",
            "publicationTitle": "The Weekly Edition",
            "trackCount": 2,
            "durationMs": 100_000,
        },
        {
            "contentId": "track-1",
            "publicationId": "publication-1",
            "publicationTitle": "The Weekly Edition",
            "trackCount": 2,
            "durationMs": 300_000,
        },
    ])["playbackQueue"]

    assert queue["publicationTrackCount"] == 2
    assert queue["publicationTotalDurationMs"] == 400_000


def test_publication_boundary_activates_feedback_only_after_finalize(mock_handler_input):
    _store(mock_handler_input)
    for index in range(7):
        FeedbackService.update_publication_progress(
            mock_handler_input, _state(index), completed=True,
        )
    assert mock_handler_input.attributes_manager.request_attributes["_store"]["awaitingFeedback"] is False

    assert FeedbackService.finalize_other_publications(
        mock_handler_input, "publication-2",
    ) is True
    FeedbackService.activate_best(mock_handler_input)

    store = mock_handler_input.attributes_manager.request_attributes["_store"]
    assert store["awaitingFeedback"] is True
    assert store["pendingFeedback"]["feedbackKey"] == "publication:publication-1"


async def _enjoy_publication(mock_handler_input, organization_name):
    pending = {
        "feedbackKey": "publication:publication-1",
        "subjectType": "publication",
        "publicationId": "publication-1",
        "title": "The Weekly Edition",
        "organizationId": "org-1",
        "organizationName": organization_name,
        "creatorId": "creator-1",
        "creatorName": "Independent Reader",
        "category": "news",
        "completed": True,
    }
    _store(mock_handler_input, awaitingFeedback=True, pendingFeedback=pending)
    mock_handler_input.request_envelope = AttrDict(mock_handler_input.request_envelope)
    mock_handler_input.request_envelope.request = AttrDict({
        "type": "IntentRequest",
        "intent": {"name": "FeedbackEnjoyedIntent", "slots": {}},
    })
    await FeedbackEnjoyedHandler().handle(mock_handler_input)
    return mock_handler_input.attributes_manager.request_attributes["_store"]["pendingFollowSource"]


@pytest.mark.asyncio
async def test_enjoyed_publication_offers_publisher_organization(mock_handler_input):
    source = await _enjoy_publication(mock_handler_input, "York Talking News")
    assert source == {"id": "org-1", "name": "York Talking News", "type": "organization"}


@pytest.mark.asyncio
async def test_independent_publication_offers_creator(mock_handler_input):
    source = await _enjoy_publication(mock_handler_input, "Independent Creator")
    assert source == {"id": "creator-1", "name": "Independent Reader", "type": "creator"}


@pytest.mark.asyncio
async def test_feedback_value_and_publication_subject_are_persisted(mock_handler_input):
    pending = {
        "feedbackKey": "publication:publication-1",
        "subjectType": "publication",
        "publicationId": "publication-1",
        "contentId": "track-7",
        "title": "The Weekly Edition",
        "organizationId": "org-1",
        "coverage": 0.54,
    }
    _store(mock_handler_input, awaitingFeedback=True, pendingFeedback=pending)

    await FeedbackService.submit(mock_handler_input, "enjoyed")

    history = mock_handler_input.attributes_manager.request_attributes["_store"]["feedbackHistory"]
    assert history[-1]["value"] == "enjoyed"
    assert history[-1]["subjectType"] == "publication"
    assert history[-1]["publicationId"] == "publication-1"
