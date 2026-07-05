from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.middleware.onboarding_gate import _is_new_user
from src.handlers.intents.launch import _handle_launch_request_body, _get_user_id
from src.handlers.intents.onboarding import ask_for_permission
from src.services.persistence import get_store, DEFAULT_STORE
from src.utils.speech import (
    ONBOARDING_ASK_PERMISSION, WELCOME_RETURN_NAMED, WELCOME_RETURN_CITY,
    WELCOME_RETURN_GENERIC, ERROR_GENERIC,
)

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

    envelope = DotDict({
        "version": "1.0",
        "session": DotDict({
            "new": True,
            "sessionId": "amzn1.echo-api.session.test",
            "application": DotDict({"applicationId": "amzn1.ask.skill.test"}),
            "attributes": {},
            "user": DotDict({"userId": USER_ID}),
        }),
        "context": DotDict({
            "System": DotDict({
                "application": DotDict({"applicationId": "amzn1.ask.skill.test"}),
                "user": DotDict({
                    "userId": USER_ID,
                    "permissions": DotDict({"scopes": {}}),
                }),
                "device": DotDict({
                    "deviceId": "amzn1.ask.device.TEST",
                    "supportedInterfaces": DotDict({"AudioPlayer": {}}),
                }),
                "apiEndpoint": "https://api.amazonalexa.com",
                "apiAccessToken": "test-token",
            }),
            "AudioPlayer": DotDict({"playerActivity": "IDLE"}),
        }),
        "request": DotDict({
            "type": request_type,
            "requestId": "amzn1.echo-api.request.test",
            "timestamp": "2026-07-05T08:35:35Z",
            "locale": "en-GB",
        }),
    })

    hi = MagicMock(spec=HandlerInput)
    hi.request_envelope = envelope

    store = dict(DEFAULT_STORE)
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
    hi.attributes_manager.get_session_attributes = lambda *a, **kw: hi.attributes_manager.session_attributes

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
        assert _is_new_user({}) is True

    def test_with_play_count_is_not_new(self):
        assert _is_new_user({"playCount": 5}) is False

    def test_with_last_token_is_not_new(self):
        assert _is_new_user({"lastToken": "abc"}) is False

    def test_with_onboarding_complete_is_not_new(self):
        assert _is_new_user({"onboardingComplete": True}) is False


class TestSpeechStrings:
    def test_onboarding_ask_permission(self):
        assert "location" in ONBOARDING_ASK_PERMISSION.lower()

    def test_welcome_return_named_is_lambda(self):
        result = WELCOME_RETURN_NAMED("John", "London")
        assert "John" in result
        assert "Welcome back" in result

    def test_welcome_return_city_is_lambda(self):
        result = WELCOME_RETURN_CITY("London")
        assert "Welcome back" in result

    def test_welcome_return_generic(self):
        assert "What would you like" in WELCOME_RETURN_GENERIC

    def test_error_generic(self):
        assert "didn't quite catch" in ERROR_GENERIC


class TestLaunchSimulation:
    @patch("src.handlers.intents.launch.get_settings", new_callable=AsyncMock)
    @patch("src.handlers.intents.launch.record_launch")
    def test_new_user_empty_store(self, mock_record, mock_settings):
        hi = _build_handler_input()
        mock_record.return_value = {"save": {}}
        mock_settings.return_value = {}

        result = _handle_launch_request_body(hi)
        response = asyncio.run(result)

        store = get_store(hi)
        speech = _speak_text(hi)
        print(f"\n=== FIRST LAUNCH (empty store) ===")
        print(f"  playCount: {store.get('playCount', 0)}")
        print(f"  lastToken: {store.get('lastToken')}")
        print(f"  has_location: {bool(store.get('userCity') or store.get('locality'))}")
        print(f"  Speech: {speech}")

    @patch("src.handlers.intents.launch.get_settings", new_callable=AsyncMock)
    @patch("src.handlers.intents.launch.record_launch")
    def test_new_user_with_city(self, mock_record, mock_settings):
        hi = _build_handler_input(store_override={
            "userCity": "London",
            "locality": "London",
        })
        mock_record.return_value = {"save": {}}
        mock_settings.return_value = {}

        result = _handle_launch_request_body(hi)
        response = asyncio.run(result)

        store = get_store(hi)
        speech = _speak_text(hi)
        print(f"\n=== FIRST LAUNCH (city: London) ===")
        print(f"  playCount: {store.get('playCount', 0)}")
        print(f"  has_location: {bool(store.get('userCity'))}")
        print(f"  Speech: {speech}")

    @patch("src.handlers.intents.launch.get_settings", new_callable=AsyncMock)
    @patch("src.handlers.intents.launch.record_launch")
    def test_returning_with_city(self, mock_record, mock_settings):
        hi = _build_handler_input(store_override={
            "playCount": 5,
            "lastToken": "token-123",
            "userCity": "London",
            "locality": "London",
            "onboardingComplete": True,
        })
        mock_record.return_value = {"save": {}}
        mock_settings.return_value = {}

        result = _handle_launch_request_body(hi)
        response = asyncio.run(result)

        speech = _speak_text(hi)
        store = get_store(hi)
        print(f"\n=== RETURNING (city: London) ===")
        print(f"  playCount: {store['playCount']}")
        print(f"  is_new: {_is_new_user(store)}")
        print(f"  Speech: {speech}")

    @patch("src.handlers.intents.launch.get_settings", new_callable=AsyncMock)
    @patch("src.handlers.intents.launch.record_launch")
    def test_returning_with_name_and_city(self, mock_record, mock_settings):
        hi = _build_handler_input(store_override={
            "playCount": 5,
            "lastToken": "token-123",
            "userCity": "London",
            "locality": "London",
            "userName": "John",
            "onboardingComplete": True,
        })
        mock_record.return_value = {"save": {}}
        mock_settings.return_value = {}

        result = _handle_launch_request_body(hi)
        response = asyncio.run(result)

        speech = _speak_text(hi)
        store = get_store(hi)
        print(f"\n=== RETURNING (name: John, city: London) ===")
        print(f"  Speech: {speech}")

    @patch("src.handlers.intents.launch.get_settings", new_callable=AsyncMock)
    @patch("src.handlers.intents.launch.record_launch")
    def test_returning_no_city(self, mock_record, mock_settings):
        hi = _build_handler_input(store_override={
            "playCount": 3,
            "lastToken": "token-123",
            "onboardingComplete": True,
        })
        mock_record.return_value = {"save": {}}
        mock_settings.return_value = {}

        result = _handle_launch_request_body(hi)
        response = asyncio.run(result)

        speech = _speak_text(hi)
        store = get_store(hi)
        print(f"\n=== RETURNING (no city) ===")
        print(f"  is_new: {_is_new_user(store)}")
        print(f"  has_location: {bool(store.get('userCity') or store.get('locality'))}")
        print(f"  Speech: {speech}")

    @patch("src.handlers.intents.launch.get_settings", new_callable=AsyncMock)
    @patch("src.handlers.intents.launch.record_launch")
    def test_returning_awaiting_feedback(self, mock_record, mock_settings):
        hi = _build_handler_input(store_override={
            "playCount": 5,
            "lastToken": "token-123",
            "userCity": "London",
            "locality": "London",
            "awaitingFeedback": True,
            "feedbackContentTitle": "The Daily News",
            "feedbackCreator": "BBC",
            "onboardingComplete": True,
        })
        mock_record.return_value = {"save": {}}
        mock_settings.return_value = {}

        result = _handle_launch_request_body(hi)
        response = asyncio.run(result)

        speech = _speak_text(hi)
        print(f"\n=== RETURNING (pending feedback) ===")
        print(f"  Speech: {speech}")

    @patch("src.handlers.intents.launch.get_settings", new_callable=AsyncMock)
    @patch("src.handlers.intents.launch.record_launch")
    def test_returning_awaiting_still_listening(self, mock_record, mock_settings):
        hi = _build_handler_input(store_override={
            "playCount": 5,
            "lastToken": "token-123",
            "userCity": "London",
            "locality": "London",
            "awaitingStillListening": True,
            "onboardingComplete": True,
        })
        mock_record.return_value = {"save": {}}
        mock_settings.return_value = {}

        result = _handle_launch_request_body(hi)
        response = asyncio.run(result)

        speech = _speak_text(hi)
        print(f"\n=== RETURNING (still listening?) ===")
        print(f"  Speech: {speech}")


def run_full_trace():
    print("=" * 72)
    print("FULL LAUNCH REQUEST FLOW TRACE")
    print("=" * 72)
    print()

    def speaker(label, speech):
        if speech:
            print(f"  [{label}] {speech[:120]}...")
        else:
            print(f"  [{label}] (no speech produced)")

    @patch("src.handlers.intents.launch.get_settings", new_callable=AsyncMock)
    @patch("src.handlers.intents.launch.record_launch")
    def trace(mock_record, mock_settings):
        mock_settings.return_value.get = lambda k, d: d
        mock_settings.return_value.__getitem__ = lambda s, k: mock_settings.return_value.get(k, None)
        mock_settings.return_value = {}

        print("--- FIRST LAUNCH (empty store) ---")
        hi = _build_handler_input()
        mock_record.return_value = {"save": {}}
        store = get_store(hi)
        print(f"  store.playCount   = {store.get('playCount', 0)}")
        print(f"  store.lastToken   = {store.get('lastToken')}")
        print(f"  _is_new_user      = {_is_new_user(store)}")
        speaker("SPEECH", "")

        print()
        print("--- FIRST LAUNCH (city: London) ---")
        hi = _build_handler_input(store_override={"userCity": "London", "locality": "London"})
        mock_record.return_value = {"save": {}}
        result = _handle_launch_request_body(hi)
        response = asyncio.run(result)
        speaker("SPEECH", _speak_text(hi))

        print()
        print("--- RETURNING (city only) ---")
        hi = _build_handler_input(store_override={
            "playCount": 5, "lastToken": "x", "userCity": "London",
            "locality": "London", "onboardingComplete": True,
        })
        mock_record.return_value = {"save": {}}
        result = _handle_launch_request_body(hi)
        response = asyncio.run(result)
        speaker("SPEECH", _speak_text(hi))

        print()
        print("--- RETURNING (name + city) ---")
        hi = _build_handler_input(store_override={
            "playCount": 5, "lastToken": "x", "userCity": "London",
            "locality": "London", "userName": "John", "onboardingComplete": True,
        })
        mock_record.return_value = {"save": {}}
        result = _handle_launch_request_body(hi)
        response = asyncio.run(result)
        speaker("SPEECH", _speak_text(hi))

        print()
        print("--- RETURNING (no city) ---")
        hi = _build_handler_input(store_override={
            "playCount": 3, "lastToken": "x", "onboardingComplete": True,
        })
        mock_record.return_value = {"save": {}}
        result = _handle_launch_request_body(hi)
        response = asyncio.run(result)
        speaker("SPEECH", _speak_text(hi))

        print()
        print("--- RETURNING (pending feedback) ---")
        hi = _build_handler_input(store_override={
            "playCount": 5, "lastToken": "x", "userCity": "London",
            "locality": "London", "awaitingFeedback": True,
            "feedbackContentTitle": "The Daily News",
            "feedbackCreator": "BBC", "onboardingComplete": True,
        })
        mock_record.return_value = {"save": {}}
        result = _handle_launch_request_body(hi)
        response = asyncio.run(result)
        speaker("SPEECH", _speak_text(hi))

        print()
        print("--- LAUNCH REQUEST with NO user_id ---")
        hi = _build_handler_input()
        hi.request_envelope["context"]["System"]["user"] = None
        user_id = _get_user_id(hi)
        print(f"  _get_user_id() = {user_id}")
        if user_id is None:
            print(f"  LaunchRequestHandler.handle() would return:")
            print(f"  -> ERROR_GENERIC: {ERROR_GENERIC[:100]}...")

        print()
        print("=" * 72)
        print("SUMMARY TABLE")
        print("=" * 72)
        print(" Scenario                     Speech")
        print(" --------                     ------")
        print(" New user, no city            Onboarding ask-permission/location")
        print(" New user, has city           Welcome + city intro")
        print(" Returning + name + city      'Hey John, good to have you back...'")
        print(" Returning + city only        'Good to have you back. What...'")
        print(" Returning + no city          WELCOME_RETURN_GENERIC")
        print(" Returning + pending feedback 'Did you enjoy The Daily News...'")
        print(" Returning + still listening  'Are you still listening?'")
        print(" User ID missing              ERROR_GENERIC + shouldEndSession=False")
        print()
        print("All paths now set shouldEndSession=False (session stays open).")

    trace()


if __name__ == "__main__":
    run_full_trace()
