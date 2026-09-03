from __future__ import annotations

import pytest

from src.alexa.runtime import AttrDict
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.controllers.feedback import FeedbackEnjoyedHandler
from src.models.feedback import FeedbackService
from src.models.playback_state import PlaybackQueue
from src.models.user import User


def _state(index: int, *, listened=60000, duration=60000, count=13):
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
        **StateSchema.DEFAULT_STORE,
        **updates,
    }


def test_six_of_thirteen_tracks_does_not_create_publication_feedback(
    mock_handler_input,
):
    _store(mock_handler_input)
    for index in range(6):
        FeedbackService.update_publication_progress(
            mock_handler_input, _state(index), completed=True
        )
    candidate = FeedbackService.finalize_publication(mock_handler_input, "publication-1")
    assert candidate is None
    assert (
        mock_handler_input.attributes_manager.request_attributes["_store"]["feedbackCandidates"]
        == []
    )
    assert (
        "publication-1"
        in mock_handler_input.attributes_manager.request_attributes["_store"][
            "publicationFeedbackProgress"
        ]
    )


def test_below_threshold_progress_accumulates_after_publication_boundary(
    mock_handler_input,
):
    _store(mock_handler_input)
    for index in range(6):
        FeedbackService.update_publication_progress(
            mock_handler_input, _state(index), completed=True
        )
    assert FeedbackService.finalize_publication(mock_handler_input, "publication-1") is None
    FeedbackService.update_publication_progress(mock_handler_input, _state(6), completed=True)
    candidate = FeedbackService.finalize_publication(mock_handler_input, "publication-1")
    assert candidate["meaningfulTrackCount"] == 7
    assert candidate["coverage"] >= 0.5


def test_seven_of_thirteen_tracks_creates_one_publication_candidate(mock_handler_input):
    _store(mock_handler_input)
    for index in range(7):
        FeedbackService.update_publication_progress(
            mock_handler_input, _state(index), completed=True
        )
    candidate = FeedbackService.finalize_publication(mock_handler_input, "publication-1")
    assert candidate["feedbackKey"] == "publication:publication-1"
    assert candidate["subjectType"] == "publication"
    assert candidate["meaningfulTrackCount"] == 7
    assert candidate["expectedTrackCount"] == 13
    assert candidate["title"] == "The Weekly Edition"


def test_duration_weighting_uses_total_publication_duration(mock_handler_input):
    _store(
        mock_handler_input,
        playbackQueue={
            "queueId": "queue-1",
            "publicationId": "publication-1",
            "publicationTrackCount": 2,
            "publicationTotalDurationMs": 400000,
            "orderedContentIds": ["track-0", "track-1"],
            "currentIndex": 0,
        },
    )
    FeedbackService.update_publication_progress(
        mock_handler_input, _state(0, listened=150000, duration=300000, count=2)
    )
    progress = FeedbackService.update_publication_progress(
        mock_handler_input, _state(1, listened=50000, duration=100000, count=2)
    )
    assert progress["coverage"] == 0.5
    assert FeedbackService.finalize_publication(mock_handler_input, "publication-1") is not None


def test_duplicate_and_out_of_order_progress_uses_maximum_per_track(mock_handler_input):
    _store(mock_handler_input)
    FeedbackService.update_publication_progress(mock_handler_input, _state(0, listened=50000))
    FeedbackService.update_publication_progress(mock_handler_input, _state(0, listened=10000))
    progress = FeedbackService.update_publication_progress(
        mock_handler_input, _state(0, listened=40000)
    )
    assert progress["tracks"]["track-0"]["listenedMs"] == 50000
    assert len(progress["tracks"]) == 1


def test_publication_hours_sum_each_track_session_without_double_counting(
    mock_handler_input,
):
    _store(mock_handler_input)
    first = {
        **_state(0, listened=60000),
        "sessionId": "track-0-session-1",
        "timeSpentMs": 1800000,
    }
    FeedbackService.update_publication_progress(mock_handler_input, first)
    FeedbackService.update_publication_progress(mock_handler_input, first)
    FeedbackService.update_publication_progress(
        mock_handler_input,
        {
            **_state(0, listened=60000),
            "sessionId": "track-0-session-2",
            "timeSpentMs": 900000,
        },
    )
    progress = FeedbackService.update_publication_progress(
        mock_handler_input,
        {
            **_state(1, listened=60000),
            "sessionId": "track-1-session-1",
            "timeSpentMs": 900000,
        },
    )

    assert progress["tracks"]["track-0"]["timeSpentMs"] == 2700000
    assert progress["tracks"]["track-0"]["timeSpentHours"] == 0.75
    assert progress["tracks"]["track-1"]["timeSpentMs"] == 900000
    assert progress["timeSpentMs"] == 3600000
    assert progress["timeSpentHours"] == 1.0
    metrics = FeedbackService.publication_listening_metrics(
        mock_handler_input.attributes_manager.request_attributes["_store"],
        "publication-1",
    )
    assert metrics["publicationTimeSpentHours"] == 1.0
    assert [track["contentId"] for track in metrics["trackListening"]] == [
        "track-0",
        "track-1",
    ]


def test_publication_total_survives_bounded_session_ledger(mock_handler_input):
    _store(mock_handler_input)
    progress = None
    for index in range(25):
        progress = FeedbackService.update_publication_progress(
            mock_handler_input,
            {
                **_state(0, listened=60000),
                "sessionId": f"track-0-session-{index}",
                "timeSpentMs": 60000,
            },
        )

    track = progress["tracks"]["track-0"]
    assert len(track["sessions"]) == 20
    assert track["timeSpentMs"] == 1500000
    assert progress["timeSpentMs"] == 1500000


def test_publication_track_never_creates_individual_candidate_mid_queue(
    mock_handler_input,
):
    _store(
        mock_handler_input,
        playbackQueue={
            "queueId": "queue-1",
            "publicationId": "publication-1",
            "publicationTrackCount": 13,
            "orderedContentIds": [f"track-{index}" for index in range(13)],
            "currentIndex": 0,
        },
    )
    candidate = FeedbackService.record_candidate(mock_handler_input, _state(0), completed=True)
    store = mock_handler_input.attributes_manager.request_attributes["_store"]
    assert candidate is None
    assert store["feedbackCandidates"] == []
    assert store["awaitingFeedback"] is False


def test_loaded_page_boundary_is_not_publication_end_when_more_pages_exist():
    state = {"contentId": "track-2", "publicationId": "publication-1"}
    store = {
        "playbackQueue": {
            "publicationId": "publication-1",
            "orderedContentIds": ["track-0", "track-1", "track-2"],
            "currentIndex": 2,
            "pagination": {"currentPage": 0, "totalPages": 4},
        }
    }
    assert FeedbackService._publication_is_last_track(state, store) is False


def test_standalone_content_keeps_individual_feedback(mock_handler_input):
    _store(mock_handler_input)
    candidate = FeedbackService.record_candidate(
        mock_handler_input,
        {
            "contentId": "standalone-1",
            "title": "Standalone story",
            "creatorId": "creator-1",
            "creatorName": "Creator One",
            "listenedMs": 120000,
            "sessionId": "session-1",
        },
        completed=True,
    )
    assert candidate["feedbackKey"] == "standalone-1"
    assert candidate["subjectType"] == "content"


def test_publication_prompt_uses_publication_wording(mock_handler_input):
    _store(
        mock_handler_input,
        awaitingFeedback=True,
        pendingFeedback={
            "feedbackKey": "publication:publication-1",
            "subjectType": "publication",
            "publicationId": "publication-1",
            "title": "The Weekly Edition",
            "completed": True,
        },
    )
    from src.alexa.feedback import AlexaFeedback

    AlexaFeedback.present_pending_feedback(
        mock_handler_input,
        mock_handler_input.attributes_manager.request_attributes["_store"],
    )
    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    assert "You listened to The Weekly Edition" in spoken
    assert "Did you enjoy this publication" in spoken


def test_publication_feedback_prefers_publication_title_in_speech_and_reprompt(
    mock_handler_input,
):
    _store(
        mock_handler_input,
        awaitingFeedback=True,
        pendingFeedback={
            "feedbackKey": "publication:publication-1",
            "subjectType": "publication",
            "publicationId": "publication-1",
            "publicationTitle": "The Weekly Edition",
            "title": "Track seven",
            "completed": True,
        },
    )
    from src.alexa.feedback import AlexaFeedback

    AlexaFeedback.present_pending_feedback(
        mock_handler_input,
        mock_handler_input.attributes_manager.request_attributes["_store"],
    )

    spoken = mock_handler_input.response_builder.speak.call_args.args[0]
    reprompt = (
        mock_handler_input.response_builder.speak.return_value.reprompt.call_args.args[0]
    )
    assert "The Weekly Edition" in spoken
    assert "The Weekly Edition" in reprompt
    assert "Track seven" not in spoken
    assert "that track" not in reprompt


def test_publication_queue_records_expected_count_and_duration(mock_handler_input):
    _store(mock_handler_input)
    queue = PlaybackQueue(User()).initialize(
        mock_handler_input,
        [
            {
                "contentId": "track-0",
                "publicationId": "publication-1",
                "publicationTitle": "The Weekly Edition",
                "trackCount": 2,
                "durationMs": 100000,
            },
            {
                "contentId": "track-1",
                "publicationId": "publication-1",
                "publicationTitle": "The Weekly Edition",
                "trackCount": 2,
                "durationMs": 300000,
            },
        ],
    )["playbackQueue"]
    assert queue["publicationTrackCount"] == 2
    assert queue["publicationTotalDurationMs"] == 400000


def test_publication_boundary_activates_feedback_only_after_finalize(
    mock_handler_input,
):
    _store(mock_handler_input)
    for index in range(7):
        FeedbackService.update_publication_progress(
            mock_handler_input, _state(index), completed=True
        )
    assert (
        mock_handler_input.attributes_manager.request_attributes["_store"]["awaitingFeedback"]
        is False
    )
    assert FeedbackService.finalize_other_publications(mock_handler_input, "publication-2") is True
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
    mock_handler_input.request_envelope.request = AttrDict(
        {
            "type": "IntentRequest",
            "intent": {"name": "FeedbackEnjoyedIntent", "slots": {}},
        }
    )
    await FeedbackEnjoyedHandler(deps=ApplicationContainer()).handle(mock_handler_input)
    return mock_handler_input.attributes_manager.request_attributes["_store"]["pendingFollowSource"]


@pytest.mark.asyncio
async def test_enjoyed_publication_offers_publisher_organization(mock_handler_input):
    source = await _enjoy_publication(mock_handler_input, "York Talking News")
    assert source == {
        "id": "org-1",
        "name": "York Talking News",
        "type": "organization",
    }


@pytest.mark.asyncio
async def test_independent_publication_offers_creator(mock_handler_input):
    source = await _enjoy_publication(mock_handler_input, "Independent Creator")
    assert source == {
        "id": "creator-1",
        "name": "Independent Reader",
        "type": "creator",
    }


@pytest.mark.asyncio
async def test_feedback_value_and_publication_subject_are_not_duplicated_locally(
    mock_handler_input,
):
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
    await FeedbackService().submit(mock_handler_input, "enjoyed")
    store = mock_handler_input.attributes_manager.request_attributes["_store"]
    assert store["feedbackHistory"] == []
    assert "publication:publication-1" in store["answeredFeedbackKeys"]
