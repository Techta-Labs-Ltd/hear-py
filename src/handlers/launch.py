from __future__ import annotations
import logging
import time
from typing import Any, Dict, Optional
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from src.services.store import get_store, update_store
from src.dependencies import Dependencies
from src.services.launch import record_launch
from src.utils.skill_request import get_user_id as get_alexa_user_id
from src.services.playback import flush_previous_track
from src.utils.skill_request import (
    get_request_type,
    get_intent_name,
    get_user_id as _get_user_id,
)
from src.utils.speech import (
    ssml,
    escape_ssml_lite,
    humanize_spoken_title,
    WELCOME_FIRST,
    WELCOME_FIRST_HAS_CITY,
    WELCOME_ERROR,
    WELCOME_REPROMPT,
    ERROR_GENERIC,
    REPROMPT_NO_CITY,
    LAUNCH_PENDING_FEEDBACK,
    FEEDBACK_AWAITING_REPROMPT,
    LAUNCH_RESUME_FLAGGED_PROMPT,
    FLAGGED_CONTINUE_REPROMPT,
)
from src.utils.lambda_deadline import get_lambda_remaining_ms
from src.handlers.onboarding import (
    ONBOARDING_ASK_TOWN,
    handle_returning_user,
    start_town_capture,
    resume_town_capture,
    stage_town_confirmation,
    finalize_town_skipped,
)
from src.handlers.search import _extract_slot_value
from src.services.playback import has_unfinished_playback, read_playback_session
from src.services.feedback import feedback_service
from src.services.dialog_state import (
    activate_dialog,
    clear_active_dialog,
    get_active_dialog,
)
logger = logging.getLogger(__name__)


def _read_cached_locality(store: Dict[str, Any]) -> Optional[str]:
    """Read cached locality from persistence store."""
    return store.get("locality")


def _listener_data_is_cached(store: Dict[str, Any]) -> bool:
    """Check whether listener profile data is still within its TTL cache window."""
    if not store:
        return False
    PROFILE_TTL_MS = 24 * 60 * 60 * 1000
    now = int(time.time() * 1000)
    resolved_at = store.get("listenerProfileResolvedAt", 0)
    has_name = bool(store.get("userName") or store.get("fullName") or store.get("givenName"))
    if not has_name and not store.get("userEmail"):
        return False
    if not resolved_at:
        return False
    return (now - resolved_at) < PROFILE_TTL_MS


async def _handle_launch_request_body(handler_input: HandlerInput, *, deps: Dependencies | None = None):
    """Core launch request logic: resolves state and routes to appropriate flow."""
    store = get_store(handler_input)
    d = deps or Dependencies()
    # A launch response replaces any unanswered discovery clarification. The
    # next explicit play request must be resolved as a new request, not as an
    # answer to an ambiguity left by an earlier session.
    if store.get("pendingAmbiguity") or store.get("awaitingOrganizationName"):
        clear_active_dialog(handler_input, "ambiguity")
        update_store(handler_input, {
            "pendingAmbiguity": None,
            "awaitingOrganizationName": False,
        })
        store = get_store(handler_input)
    user_id = _get_user_id(handler_input)
    user_name = store.get("userName") or store.get("givenName") or store.get("fullName")

    launch = record_launch(user_id, store)
    if launch.get("save"):
        update_store(handler_input, launch["save"])
        store = get_store(handler_input)

    # Foreground interaction priority: onboarding, resume, then feedback.
    if store.get("onboardingStage") == "confirm_town_for_community":
        return start_town_capture(handler_input, store, user_name)

    if has_unfinished_playback(store):
        active = read_playback_session(store) or {}
        title = escape_ssml_lite(active.get("title") or "your recording")
        update_store(handler_input, {"awaitingResume": True})
        activate_dialog(handler_input, "resume", context=active)
        return handler_input.response_builder \
            .speak(ssml(f"You did not finish {title}. Would you like to continue?")) \
            .reprompt(ssml("Would you like to continue listening?")) \
            .set_should_end_session(False) \
            .response

    if store.get("awaitingContinueAfterFlag"):
        return handler_input.response_builder \
            .speak(ssml(LAUNCH_RESUME_FLAGGED_PROMPT)) \
            .reprompt(FLAGGED_CONTINUE_REPROMPT) \
            .set_should_end_session(False) \
            .response

    if store.get("awaitingFeedback") and store.get("pendingFeedback"):
        return feedback_service.pending_response(handler_input)

    if store.get("awaitingFeedback") and (store.get("feedbackContentTitle") or store.get("feedbackPromptText")):
        await d.alexa.cancel_feedback_reminder(handler_input)
        title_humanized = humanize_spoken_title(store.get("feedbackContentTitle")) or "that track"
        creator_escaped = escape_ssml_lite(store.get("feedbackCreator") or "the creator")
        fb_prompt = LAUNCH_PENDING_FEEDBACK(title_humanized, creator_escaped, user_name)
        builder = d.locality.attach_profile_permission_if_needed(
            handler_input.response_builder
                .speak(ssml(fb_prompt))
                .reprompt(ssml(FEEDBACK_AWAITING_REPROMPT)),
            handler_input, store,
        )
        return builder.set_should_end_session(False).response

    try:
        store = await _ensure_listener_data_for_launch(handler_input, store)
    except Exception:
        pass

    resolved_user_name = store.get("userName") or store.get("givenName") or store.get("fullName")
    resolved_locality = _read_cached_locality(store)
    has_location = bool(store.get("userCity") or store.get("locality"))
    is_first_time = store.get("playCount", 0) == 0 and not store.get("lastToken")
    city = store.get("userCity") or store.get("locality")

    _schedule_launch_background_work(handler_input, store)

    if is_first_time and has_location:
        return handler_input.response_builder \
            .speak(ssml(WELCOME_FIRST_HAS_CITY(resolved_user_name, city))) \
            .set_should_end_session(False) \
            .response

    if is_first_time:
        return handler_input.response_builder \
            .speak(ssml(WELCOME_FIRST(resolved_user_name))) \
            .set_should_end_session(False) \
            .response

    if not is_first_time and has_location:
        return handle_returning_user(handler_input, store, resolved_user_name, resolved_locality)

    return handle_returning_user(handler_input, store, resolved_user_name, None)


async def _ensure_listener_data_for_launch(handler_input: HandlerInput, store: Dict[str, Any]):
    """Enrich listener profile data on launch if budget allows."""
    remaining = get_lambda_remaining_ms(handler_input)
    if isinstance(remaining, (int, float)) and remaining < 3500:
        logger.info("Hear: launch enrichment skipped (budget) remainingMs=%s", remaining)
        return store

    enriched = store
    try:
        if not _listener_data_is_cached(store):
            enriched = await d.locality.apply_listener_profile(handler_input)
            logger.info("Hear: launch enrichment done")
    except Exception as err:
        logger.warning("Hear: launch enrichment failed %s", err)

    return enriched


def _schedule_launch_background_work(handler_input: HandlerInput, store: Dict[str, Any]):
    """Retain the launch scheduling seam for callers."""
    del handler_input, store


class LaunchRequestHandler(AbstractRequestHandler):
    """Handles Alexa LaunchRequest — the skill entry point."""

    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return get_request_type(handler_input) == "LaunchRequest"

    async def handle(self, handler_input: HandlerInput):
        user_id = _get_user_id(handler_input)
        if not user_id:
            return handler_input.response_builder \
                .speak(ssml(ERROR_GENERIC)) \
                .reprompt(ssml(WELCOME_REPROMPT)) \
                .set_should_end_session(False) \
                .response

        try:
            await flush_previous_track(get_alexa_user_id(handler_input), None, handler_input)
        except Exception as err:
            logger.warning("Hear: launch flush failed error=%s", type(err).__name__)

        try:
            return await _handle_launch_request_body(handler_input, deps=self._deps)
        except Exception as err:
            logger.error("Hear: launch failed %s", err)
            return handler_input.response_builder \
                .speak(ssml(WELCOME_ERROR)) \
                .reprompt(ssml(REPROMPT_NO_CITY)) \
                .set_should_end_session(False) \
                .response


class TownCaptureHandler(AbstractRequestHandler):

    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input: HandlerInput) -> bool:
        if get_request_type(handler_input) != "IntentRequest":
            return False
        store = get_store(handler_input)
        if store.get("onboardingStage") != ONBOARDING_ASK_TOWN:
            return False

        active_dialog = get_active_dialog(handler_input)
        if active_dialog and active_dialog.get("type") != "onboarding":
            return False

        attrs = handler_input.attributes_manager.get_request_attributes()
        nlp_intent = (attrs or {}).get("_nlp", {}).get("intent")
        if nlp_intent == "town_capture":
            return True
        if nlp_intent:
            return False

        intent_name = get_intent_name(handler_input)
        return intent_name in (
            "TownCaptureIntent",
            "SetLocationIntent",
            "AMAZON.NoIntent",
            "SkipFeedbackIntent",
            "AMAZON.CancelIntent",
        )

    async def handle(self, handler_input: HandlerInput):
        store = get_store(handler_input)
        intent_name = get_intent_name(handler_input)

        if intent_name in ("AMAZON.NoIntent", "SkipFeedbackIntent", "AMAZON.CancelIntent"):
            return finalize_town_skipped(handler_input, store)

        attrs = handler_input.attributes_manager.get_request_attributes()
        nlp = attrs.get("_nlp", {}) if attrs else {}
        nlp_slots = nlp.get("slots", {}) if nlp else {}
        nlp_town = nlp_slots.get("townName") or nlp_slots.get("placeName")
        if not nlp_town:
            nlp_town = (
                _extract_slot_value(handler_input, "townName")
                or _extract_slot_value(handler_input, "location")
            )

        if nlp_town:
            return await stage_town_confirmation(handler_input, store, nlp_town, deps=self._deps)

        return resume_town_capture(handler_input, store)


class SetLocationHandler(AbstractRequestHandler):
    def __init__(self, *, deps: Dependencies | None = None):
        self._deps = deps or Dependencies()

    def can_handle(self, handler_input: HandlerInput) -> bool:
        attrs = handler_input.attributes_manager.get_request_attributes()
        return bool(attrs) and attrs.get("_nlp", {}).get("intent") == "location_set"

    async def handle(self, handler_input: HandlerInput):
        attrs = handler_input.attributes_manager.get_request_attributes()
        nlp = attrs.get("_nlp", {}) if attrs else {}
        town = (nlp.get("slots", {}) or {}).get("townName")

        if town:
            return await stage_town_confirmation(handler_input, get_store(handler_input), town, deps=self._deps)

        update_store(handler_input, {
            "onboardingStage": ONBOARDING_ASK_TOWN,
            "onboardingTownAttempts": 0,
        })
        return handler_input.response_builder \
            .speak(ssml("Sure. Which town or city are you in now?")) \
            .reprompt(ssml("Which town or city should I set as your location?")) \
            .set_should_end_session(False) \
            .response
