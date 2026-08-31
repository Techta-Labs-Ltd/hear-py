from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.alexa.speech import Speech
from src.constants.state import StateSchema
from src.container import ApplicationContainer
from src.middleware.onboarding_gate import OnboardingPolicy
from src.models.launch_workflow import LaunchWorkflow
from src.models.user import User

USER_ID = "amzn1.ask.account.AMA5VNMEKZ2IKKQ66FJFFNUFHIZWGKDJXHMTPAWPFIW6Q7NFOQDKCSUNC44TFDRZXRIMA7YZUNKJHK2KAVHFCOAQSSSLDEYEFMJYXTZYYOYK52IGMJMU3KWXBZPGNEUJC4HAKIJUSUZDKD3GRL26OQMBR4BPLCMTN4AVAML7OWIYSU5YAPQOTGCEEPHAMQQFZ4B7EEYUT5H56XOI3SQZ3P5S7IOVYU2UZJJXPGKLG2UA"


def _build_handler_input(request_type="LaunchRequest", store_override=None, persistent_attrs=None):
    from ask_sdk_core.handler_input import HandlerInput

    class DotDict(dict):
        def __getattr__(self, key):
            val = self.get(key)
            if val is None:
                return None
            if isinstance(val, dict):
                return DotDict(val)
            return val

    envelope = DotDict(
        {
            "version": "1.0",
            "session": DotDict(
                {
                    "new": True,
                    "sessionId": "amzn1.echo-api.session.test",
                    "application": DotDict({"applicationId": "amzn1.ask.skill.test"}),
                    "attributes": {},
                    "user": DotDict({"userId": USER_ID}),
                }
            ),
            "context": DotDict(
                {
                    "System": DotDict(
                        {
                            "application": DotDict({"applicationId": "amzn1.ask.skill.test"}),
                            "user": DotDict(
                                {
                                    "userId": USER_ID,
                                    "permissions": DotDict({"scopes": {}}),
                                }
                            ),
                            "device": DotDict(
                                {
                                    "deviceId": "amzn1.ask.device.TEST",
                                    "supportedInterfaces": DotDict({"AudioPlayer": {}}),
                                }
                            ),
                            "apiEndpoint": "https://api.amazonalexa.com",
                            "apiAccessToken": "test-token",
                        }
                    ),
                    "AudioPlayer": DotDict({"playerActivity": "IDLE"}),
                }
            ),
            "request": DotDict(
                {
                    "type": request_type,
                    "requestId": "amzn1.echo-api.request.test",
                    "timestamp": "2026-07-05T08:35:35Z",
                    "locale": "en-GB",
                }
            ),
        }
    )
    hi = MagicMock(spec=HandlerInput)
    hi.request_envelope = envelope
    store = dict(StateSchema.DEFAULT_STORE)
    if store_override:
        store.update(store_override)
    attrs = {"_store": store, "_dirty": False}
    hi.attributes_manager = MagicMock()
    hi.attributes_manager.request_attributes = attrs
    hi.attributes_manager.get_request_attributes = lambda *a, **kw: attrs
    hi.attributes_manager.set_request_attributes = MagicMock()
    hi.attributes_manager.persistent_attributes = persistent_attrs or {}
    hi.attributes_manager.get_persistent_attributes = AsyncMock(return_value=persistent_attrs or {})
    hi.attributes_manager.save_persistent_attributes = AsyncMock()
    hi.attributes_manager.session_attributes = {}
    hi.attributes_manager.set_session_attributes = MagicMock()
    hi.attributes_manager.get_session_attributes = lambda *a, **kw: (
        hi.attributes_manager.session_attributes
    )
    response_builder = MagicMock()
    hi.response_builder = response_builder
    hi.service_client_factory = MagicMock()
    hi.context = MagicMock()
    hi.request = envelope["request"]
    return hi


def _speak_text(handler_input):
    calls = handler_input.response_builder.speak.call_args_list
    if calls:
        raw = calls[0][0][0]
        return str(raw)
    return None


class TestIsNewUser:
    def test_empty_store_is_new(self):
        assert OnboardingPolicy._is_new_user({}) is True

    def test_with_play_count_is_not_new(self):
        assert OnboardingPolicy._is_new_user({"playCount": 5}) is False

    def test_with_last_token_is_not_new(self):
        assert OnboardingPolicy._is_new_user({"lastToken": "abc"}) is False

    def test_with_onboarding_complete_is_not_new(self):
        assert OnboardingPolicy._is_new_user({"onboardingComplete": True}) is False


class TestSpeechStrings:
    def test_onboarding_ask_permission(self):
        assert "location" in Speech.ONBOARDING_ASK_PERMISSION.lower()

    def test_welcome_return_named_is_lambda(self):
        result = Speech.WELCOME_RETURN_NAMED("John", "London")
        assert "John" in result
        assert "Welcome back" in result

    def test_welcome_return_city_is_lambda(self):
        result = Speech.WELCOME_RETURN_CITY("London")
        assert "Welcome back" in result

    def test_welcome_return_generic(self):
        assert "What would you like" in Speech.WELCOME_RETURN_GENERIC

    def test_error_generic(self):
        assert "didn't quite catch" in Speech.ERROR_GENERIC


class TestLaunchSimulation:
    @pytest.mark.asyncio
    async def test_launch_enrichment_uses_injected_locality_dependency(self):
        hi = _build_handler_input(store_override={"onboardingComplete": True})
        enriched = {**User.snapshot(hi), "userCity": "Wakefield"}
        listener_profile = MagicMock()
        listener_profile.apply_listener_profile = AsyncMock(return_value=enriched)
        workflow = LaunchWorkflow(deps=ApplicationContainer(listener_profile=listener_profile))
        result = await workflow._ensure_listener_data_for_launch(hi, User.snapshot(hi))
        listener_profile.apply_listener_profile.assert_awaited_once_with(hi)
        assert result["userCity"] == "Wakefield"

    @pytest.mark.asyncio
    async def test_launch_clears_stale_discovery_clarification(self, monkeypatch):
        pending = {
            "intent": "organization",
            "candidates": [
                {
                    "type": "organization",
                    "id": "org-walsall",
                    "name": "Walsall Talking Newspaper",
                }
            ],
            "expiresAt": 4102444800,
        }
        hi = _build_handler_input(
            store_override={
                "playCount": 5,
                "lastToken": "token-123",
                "onboardingComplete": True,
                "pendingAmbiguity": pending,
                "awaitingOrganizationName": True,
                "activeDialog": {
                    "type": "ambiguity",
                    "context": pending,
                    "expiresAt": 4102444800,
                },
            }
        )
        monkeypatch.setattr(
            "src.models.onboarding.LaunchTracker.record", lambda *_args: {"save": {}}
        )
        monkeypatch.setattr(
            "src.models.launch_workflow.LaunchWorkflow._ensure_listener_data_for_launch",
            AsyncMock(side_effect=lambda _handler_input, store, **_kwargs: store),
        )
        monkeypatch.setattr(
            "src.models.launch_workflow.LaunchWorkflow._schedule_launch_background_work",
            lambda *_args: None,
        )
        await LaunchWorkflow(deps=ApplicationContainer()).execute(hi)
        store = User.snapshot(hi)
        assert store["pendingAmbiguity"] is None
        assert store["awaitingOrganizationName"] is False
        assert store["activeDialog"] is None

    @pytest.mark.asyncio
    async def test_launch_clears_stale_search_confirmation_without_durable_state_loss(
        self, monkeypatch
    ):
        resolution = {
            "confirmationLabel": "sport",
            "searchPayload": {"query": "sport"},
            "expiresAt": 4102444800,
        }
        playback = {"token": "token-123", "title": "Self Control.mp3"}
        feedback = {"contentId": "content-123"}
        hi = _build_handler_input(
            store_override={
                "playCount": 5,
                "onboardingComplete": True,
                "awaitingSearchConfirmation": True,
                "pendingResolution": resolution,
                "pendingSuggestions": [{"label": "news"}],
                "suggestionIndex": 1,
                "excludedSuggestions": ["sport"],
                "activeDialog": {
                    "type": "search_confirmation",
                    "context": resolution,
                    "expiresAt": 4102444800,
                },
                "activePlayback": playback,
                "pendingFeedback": feedback,
                "followedCreators": ["creator-123"],
                "userCity": "Pendle",
            }
        )
        monkeypatch.setattr(
            "src.models.onboarding.LaunchTracker.record", lambda *_args: {"save": {}}
        )
        monkeypatch.setattr(
            "src.models.playback.PlaybackState.has_unfinished",
            lambda _self, _store: False,
        )
        monkeypatch.setattr(
            "src.models.launch_workflow.LaunchWorkflow._ensure_listener_data_for_launch",
            AsyncMock(side_effect=lambda _handler_input, store, **_kwargs: store),
        )
        monkeypatch.setattr(
            "src.models.launch_workflow.LaunchWorkflow._schedule_launch_background_work",
            lambda *_args: None,
        )
        await LaunchWorkflow(deps=ApplicationContainer()).execute(hi)
        store = User.snapshot(hi)
        assert store["awaitingSearchConfirmation"] is False
        assert store["pendingResolution"] is None
        assert store["pendingSuggestions"] == []
        assert store["suggestionIndex"] == 0
        assert store["excludedSuggestions"] == []
        assert store["activeDialog"] is None
        assert store["activePlayback"] == playback
        assert store["pendingFeedback"] == feedback
        assert store["followedCreators"] == ["creator-123"]
        assert store["userCity"] == "Pendle"

    @patch("src.models.onboarding.LaunchTracker.record")
    def test_new_user_empty_store(self, mock_record):
        hi = _build_handler_input()
        mock_record.return_value = {"save": {}}
        result = LaunchWorkflow(deps=ApplicationContainer()).execute(hi)
        asyncio.run(result)
        store = User.snapshot(hi)
        speech = _speak_text(hi)
        print("\n=== FIRST LAUNCH (empty store) ===")
        print(f"  playCount: {store.get('playCount', 0)}")
        print(f"  lastToken: {store.get('lastToken')}")
        print(f"  has_location: {bool(store.get('userCity') or store.get('locality'))}")
        print(f"  Speech: {speech}")

    @patch("src.models.onboarding.LaunchTracker.record")
    def test_new_user_with_city(self, mock_record):
        hi = _build_handler_input(store_override={"userCity": "London", "locality": "London"})
        mock_record.return_value = {"save": {}}
        result = LaunchWorkflow(deps=ApplicationContainer()).execute(hi)
        asyncio.run(result)
        store = User.snapshot(hi)
        speech = _speak_text(hi)
        print("\n=== FIRST LAUNCH (city: London) ===")
        print(f"  playCount: {store.get('playCount', 0)}")
        print(f"  has_location: {bool(store.get('userCity'))}")
        print(f"  Speech: {speech}")

    @patch("src.models.onboarding.LaunchTracker.record")
    def test_returning_with_city(self, mock_record):
        hi = _build_handler_input(
            store_override={
                "playCount": 5,
                "lastToken": "token-123",
                "userCity": "London",
                "locality": "London",
                "onboardingComplete": True,
            }
        )
        mock_record.return_value = {"save": {}}
        result = LaunchWorkflow(deps=ApplicationContainer()).execute(hi)
        asyncio.run(result)
        speech = _speak_text(hi)
        store = User.snapshot(hi)
        print("\n=== RETURNING (city: London) ===")
        print(f"  playCount: {store['playCount']}")
        print(f"  is_new: {OnboardingPolicy._is_new_user(store)}")
        print(f"  Speech: {speech}")

    @patch("src.models.onboarding.LaunchTracker.record")
    def test_returning_with_name_and_city(self, mock_record):
        hi = _build_handler_input(
            store_override={
                "playCount": 5,
                "lastToken": "token-123",
                "userCity": "London",
                "locality": "London",
                "userName": "John",
                "onboardingComplete": True,
            }
        )
        mock_record.return_value = {"save": {}}
        result = LaunchWorkflow(deps=ApplicationContainer()).execute(hi)
        asyncio.run(result)
        speech = _speak_text(hi)
        User.snapshot(hi)
        print("\n=== RETURNING (name: John, city: London) ===")
        print(f"  Speech: {speech}")

    @patch("src.models.onboarding.LaunchTracker.record")
    def test_returning_no_city(self, mock_record):
        hi = _build_handler_input(
            store_override={
                "playCount": 3,
                "lastToken": "token-123",
                "onboardingComplete": True,
            }
        )
        mock_record.return_value = {"save": {}}
        result = LaunchWorkflow(deps=ApplicationContainer()).execute(hi)
        asyncio.run(result)
        speech = _speak_text(hi)
        store = User.snapshot(hi)
        print("\n=== RETURNING (no city) ===")
        print(f"  is_new: {OnboardingPolicy._is_new_user(store)}")
        print(f"  has_location: {bool(store.get('userCity') or store.get('locality'))}")
        print(f"  Speech: {speech}")

    @patch("src.models.onboarding.LaunchTracker.record")
    def test_returning_awaiting_feedback(self, mock_record):
        hi = _build_handler_input(
            store_override={
                "playCount": 5,
                "lastToken": "token-123",
                "userCity": "London",
                "locality": "London",
                "awaitingFeedback": True,
                "feedbackContentTitle": "The Daily News",
                "feedbackCreator": "BBC",
                "onboardingComplete": True,
            }
        )
        mock_record.return_value = {"save": {}}
        result = LaunchWorkflow(deps=ApplicationContainer()).execute(hi)
        asyncio.run(result)
        speech = _speak_text(hi)
        print("\n=== RETURNING (pending feedback) ===")
        print(f"  Speech: {speech}")

    @patch("src.models.onboarding.LaunchTracker.record")
    def test_returning_awaiting_still_listening(self, mock_record):
        hi = _build_handler_input(
            store_override={
                "playCount": 5,
                "lastToken": "token-123",
                "userCity": "London",
                "locality": "London",
                "awaitingStillListening": True,
                "onboardingComplete": True,
            }
        )
        mock_record.return_value = {"save": {}}
        result = LaunchWorkflow(deps=ApplicationContainer()).execute(hi)
        asyncio.run(result)
        speech = _speak_text(hi)
        print("\n=== RETURNING (still listening?) ===")
        print(f"  Speech: {speech}")
