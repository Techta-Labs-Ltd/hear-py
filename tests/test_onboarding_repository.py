from __future__ import annotations

from src.models.onboarding_state import OnboardingService, OnboardingState
from src.models.user import User


def build_service() -> OnboardingService:
    return OnboardingService(OnboardingState(User()))


def test_onboarding_repository_has_no_arbitrary_patch_api():
    repository = OnboardingState(User())
    assert not hasattr(repository, "patch")


def test_stage_confirmation_updates_store_and_session(mock_handler_input):
    match = {"city": "Swindon", "locality": "Swindon", "countryCode": "GB"}
    build_service().stage_confirmation(mock_handler_input, match)
    store = User.snapshot(mock_handler_input)
    assert store["pendingLocationConfirm"] == match
    assert store["awaitingLocationConfirm"] is True
    assert store["onboardingStage"] == "await_location_confirm"
    assert store["_requiresReliableSave"] is True
    session = mock_handler_input.attributes_manager.set_session_attributes.call_args.args[0]
    assert session["pendingLocationConfirm"] == match
    assert session["awaitingLocationConfirm"] is True
    assert session["onboardingStage"] == "await_location_confirm"


def test_complete_location_owns_persisted_and_session_transition(mock_handler_input):
    match = {
        "city": "Manchester",
        "locality": "Manchester",
        "countryCode": "GB",
        "postalCode": "M1",
        "latitude": 53.4808,
        "longitude": -2.2426,
        "source": "device",
    }
    build_service().complete_location(
        mock_handler_input,
        match,
        offer_community_playback=True,
        preserve_postal_code=True,
    )
    store = User.snapshot(mock_handler_input)
    assert store["userCity"] == "Manchester"
    assert store["devicePostalCode"] == "M1"
    assert store["locationSource"] == "device"
    assert store["onboardingComplete"] is True
    assert store["awaitingLocationConfirm"] is False
    assert store["awaitingCommunityPlayback"] is True
    session = mock_handler_input.attributes_manager.set_session_attributes.call_args.args[0]
    assert session["onboardingComplete"] is True
    assert session["awaitingLocationConfirm"] is False
    assert session["awaitingCommunityPlayback"] is True
