from __future__ import annotations

import re
import time
from copy import deepcopy
from difflib import SequenceMatcher

from src.alexa.context import RequestContext
from src.alexa.request import AlexaRequest
from src.alexa.runtime import AttrDict
from src.constants.dialog import DialogConstants
from src.constants.discovery import DiscoveryConstants
from src.models.user import User


class DialogSelection:
    __slots__ = ()

    @staticmethod
    def normalize(value: object) -> str:
        raw = str(value or "").strip().casefold()
        raw = raw.replace("&", " and ")
        for apostrophe in ("'", "’", "‘", "ʼ", "`"):
            raw = raw.replace(apostrophe, "")
        return re.sub(r"[^a-z0-9]+", " ", raw).strip()

    @staticmethod
    def normalize_ordinal(value: object) -> str:
        raw = DialogSelection.normalize(value)
        raw = raw.replace("1st", "first").replace("2nd", "second").replace("3rd", "third")
        raw = raw.replace("4th", "fourth").replace("5th", "fifth").replace("6th", "sixth")
        raw = re.sub("^(?:the\\s+)", "", raw)
        return re.sub("\\s+(?:one|option|choice)$", "", raw)

    @staticmethod
    def unique_candidates(candidates: list[dict]) -> list[dict]:
        seen: set[str] = set()
        unique = []
        for candidate in candidates:
            name = str(candidate.get("name") or "").strip()
            key = name.casefold()
            if name and key not in seen:
                seen.add(key)
                unique.append(candidate)
        return unique

    @staticmethod
    def request_slots(handler_input) -> dict:
        request = AlexaRequest.read(handler_input.request_envelope, "request")
        intent = AlexaRequest.read(request, "intent")
        if not intent:
            return {}
        slots = intent.get("slots") if hasattr(intent, "get") else None
        return slots or AlexaRequest.read(intent, "slots") or {}

    @staticmethod
    def _selection_slot(handler_input):
        return AlexaRequest.read(DialogSelection.request_slots(handler_input), "selection")

    @staticmethod
    def _resolved_candidate(handler_input, candidates: list[dict]) -> dict | None:
        resolved_id = AlexaRequest.get_resolved_slot_id(
            DialogSelection._selection_slot(handler_input)
        )
        if not resolved_id:
            return None
        return next(
            (candidate for candidate in candidates if candidate.get("id") == resolved_id),
            None,
        )

    @staticmethod
    def choices(pending: dict) -> list[dict]:
        return list(
            pending.get("choiceCandidates")
            or DialogSelection.unique_candidates(list(pending.get("candidates") or []))
        )

    @staticmethod
    def _selection_text(value: object) -> str:
        text = DialogSelection.normalize_ordinal(value)
        text = re.sub(
            r"^(?:(?:please\s+)?(?:play|choose|select|pick)|i\s+meant)\s+",
            "",
            text,
        )
        return re.sub(r"\s+(?:please|one)$", "", text).strip()

    @staticmethod
    def _common_prefix_words(candidate_names: list[str]) -> list[str]:
        if not candidate_names:
            return []
        words = [name.split() for name in candidate_names]
        prefix: list[str] = []
        for values in zip(*words):
            if len(set(values)) != 1:
                break
            prefix.append(values[0])
        return prefix

    @staticmethod
    def closest_candidate(raw: object, candidates: list[dict]) -> dict | None:
        """Return one confident ASR-tolerant match, never an arbitrary nearest item."""
        choices = DialogSelection.unique_candidates(candidates)
        raw_key = DialogSelection._selection_text(raw)
        if not raw_key or not choices:
            return None
        names = [DialogSelection.normalize(choice.get("name")) for choice in choices]
        exact = [
            choice
            for choice, name in zip(choices, names)
            if raw_key == name
            or (len(raw_key) >= 3 and raw_key in name)
            or (len(name) >= 3 and name in raw_key)
        ]
        if len(exact) == 1:
            return exact[0]

        prefix_words = DialogSelection._common_prefix_words(names)
        raw_words = raw_key.split()
        if prefix_words and len(raw_words) <= len(prefix_words):
            prefix_score = SequenceMatcher(
                None, "".join(raw_words), "".join(prefix_words)
            ).ratio()
            if prefix_score >= 0.78:
                return None

        raw_suffix = raw_words
        if prefix_words and len(raw_words) > len(prefix_words):
            spoken_prefix = raw_words[: len(prefix_words)]
            prefix_score = SequenceMatcher(
                None, "".join(spoken_prefix), "".join(prefix_words)
            ).ratio()
            if prefix_score >= 0.72:
                raw_suffix = raw_words[len(prefix_words) :]

        scores: list[tuple[float, dict]] = []
        compact_raw = "".join(raw_words)
        compact_suffix = "".join(raw_suffix)
        for choice, name in zip(choices, names):
            full_score = SequenceMatcher(None, compact_raw, name.replace(" ", "")).ratio()
            candidate_suffix = name.split()[len(prefix_words) :]
            suffix_score = (
                SequenceMatcher(None, compact_suffix, "".join(candidate_suffix)).ratio()
                if compact_suffix and candidate_suffix
                else 0.0
            )
            scores.append((max(full_score, suffix_score), choice))
        scores.sort(key=lambda item: item[0], reverse=True)
        best_score, best = scores[0]
        next_score = scores[1][0] if len(scores) > 1 else 0.0
        threshold = 0.68 if len(compact_raw) >= 5 else 0.80
        if best_score >= threshold and best_score - next_score >= 0.08:
            return best
        return None

    @staticmethod
    def match_pending_candidate(handler_input, pending: dict, raw: str) -> dict | None:
        candidates = list(pending.get("candidates") or [])
        resolved = DialogSelection._resolved_candidate(handler_input, candidates)
        if resolved:
            return resolved
        choices = DialogSelection.choices(pending)
        displayed = list(pending.get("displayedCandidates") or choices[:3])
        raw_key = DialogSelection.normalize_ordinal(raw)
        ordinal = DiscoveryConstants.ORDINAL_INDEX.get(raw_key)
        if ordinal is not None and ordinal < len(displayed):
            return displayed[ordinal]
        return DialogSelection.closest_candidate(raw_key, choices)

    @staticmethod
    def request_candidate(handler_input, pending: dict) -> dict | None:
        candidates = DialogSelection.choices(pending)
        resolved = DialogSelection._resolved_candidate(handler_input, candidates)
        if resolved:
            return resolved
        for slot in DialogSelection.request_slots(handler_input).values():
            value = AlexaRequest.get_resolved_slot_value(slot)
            if not value:
                continue
            candidate = DialogSelection.closest_candidate(value, candidates)
            if candidate:
                return candidate
        return None

    @staticmethod
    def has_more_pages(pending: dict) -> bool:
        pagination = pending.get("candidatePagination") or {}
        current_page = max(0, int(pagination.get("currentPage") or 0))
        total_pages = max(0, int(pagination.get("totalPages") or 0))
        return total_pages > 0 and current_page + 1 < total_pages

    @staticmethod
    def has_more_choices(pending: dict, candidates: list[dict], next_offset: int) -> bool:
        return next_offset < len(candidates) or DialogSelection.has_more_pages(pending)


class DialogStateManager:
    __slots__ = ()

    @staticmethod
    def _now() -> int:
        return int(time.time())

    @staticmethod
    def active_from_store(store: dict | None) -> dict | None:
        return User.active_dialog(store)

    @staticmethod
    def get_active(handler_input) -> dict | None:
        return DialogStateManager.active_from_store(User.snapshot(handler_input))

    @staticmethod
    def activate(
        handler_input,
        dialog_type: str,
        *,
        context: dict | None = None,
        deferred_request: dict | None = None,
        ttl_seconds: int = DialogConstants.DIALOG_TTL_SECONDS,
    ) -> dict:
        now = DialogStateManager._now()
        active = {
            "type": dialog_type,
            "context": deepcopy(context or {}),
            "deferredRequest": deepcopy(deferred_request) if deferred_request else None,
            "createdAt": now,
            "expiresAt": now + max(1, int(ttl_seconds)),
        }
        updates = {flag: False for flag in DialogConstants.DIALOG_LEGACY_FLAGS.values()}
        legacy_flag = DialogConstants.DIALOG_LEGACY_FLAGS.get(dialog_type)
        if legacy_flag:
            updates[legacy_flag] = True
        updates.update({"activeDialog": active, "_requiresReliableSave": True})
        return User.update(handler_input, updates)

    @staticmethod
    def clear(handler_input, *dialog_types: str) -> dict:
        store = User.snapshot(handler_input)
        raw_active = store.get("activeDialog")
        active = (
            raw_active
            if isinstance(raw_active, dict) and raw_active.get("type")
            else DialogStateManager.active_from_store(store)
        )
        if dialog_types and (not active or active.get("type") not in dialog_types):
            return store
        updates = {"activeDialog": None}
        if active and active.get("type") in DialogConstants.DIALOG_LEGACY_FLAGS:
            updates[DialogConstants.DIALOG_LEGACY_FLAGS[active["type"]]] = False
        return User.update(handler_input, updates)

    @staticmethod
    def clear_transient_discovery(handler_input) -> dict:
        """Discard discovery choices that are only valid in the current session."""
        store = User.snapshot(handler_input)
        raw_active = store.get("activeDialog")
        active_type = raw_active.get("type") if isinstance(raw_active, dict) else None
        updates = {
            "awaitingSearchConfirmation": False,
            "pendingResolution": None,
            "pendingAmbiguity": None,
            "pendingSuggestions": [],
            "suggestionIndex": 0,
            "excludedSuggestions": [],
            "awaitingOrganizationName": False,
            "awaitingCreatorName": False,
            "_requiresReliableSave": True,
        }
        if active_type in DialogConstants.TRANSIENT_DISCOVERY_DIALOGS or (
            not active_type
            and (
                store.get("awaitingSearchConfirmation")
                or store.get("pendingResolution")
                or store.get("pendingAmbiguity")
            )
        ):
            updates["activeDialog"] = None
        return User.update(handler_input, updates)

    @staticmethod
    def dismiss_ambiguity(handler_input) -> dict:
        """Dismiss the current ambiguity without ending the Alexa session."""
        return User.update(
            handler_input,
            {
                "pendingAmbiguity": None,
                "activeDialog": None,
                "_requiresReliableSave": True,
            },
        )

    @staticmethod
    def migrate(store: dict) -> dict:
        return User.migrate_dialog(store)


class DeferredIntentManager:
    __slots__ = ()

    @staticmethod
    def _can_defer(handler_input) -> bool:
        return (
            AlexaRequest.get_request_type(handler_input) == "IntentRequest"
            and AlexaRequest.get_intent_name(handler_input)
            in DialogConstants.DEFERRED_DISCOVERY_INTENTS
        )

    @staticmethod
    def capture(handler_input) -> bool:
        if not DeferredIntentManager._can_defer(handler_input):
            return False
        request = handler_input.request_envelope.request
        attrs = RequestContext.request(handler_input)
        deferred = {
            "intent": deepcopy(dict(request.intent)),
            "nlp": deepcopy((attrs or {}).get("_nlp") or {}),
            "pendingConfirmation": deepcopy((attrs or {}).get("_pendingConfirmation") or {}),
        }
        User.update(handler_input, {"deferredIntent": deferred})
        store = User.snapshot(handler_input)
        DialogStateManager.activate(
            handler_input,
            "feedback",
            context=store.get("pendingFeedback") or {},
            deferred_request=deferred,
        )
        return True

    @staticmethod
    def has(handler_input) -> bool:
        return isinstance(User.snapshot(handler_input).get("deferredIntent"), dict)

    @staticmethod
    async def resume(handler_input):
        deferred = User.snapshot(handler_input).get("deferredIntent")
        if not isinstance(deferred, dict) or not isinstance(deferred.get("intent"), dict):
            return None
        User.update(handler_input, {"deferredIntent": None})
        handler_input.request_envelope.request.intent = AttrDict(deferred["intent"])
        attrs = RequestContext.request(handler_input)
        attrs["_nlp"] = deepcopy(deferred.get("nlp") or {})
        pending = deferred.get("pendingConfirmation")
        if isinstance(pending, dict) and pending.get("resolution"):
            attrs["_pendingConfirmation"] = deepcopy(pending)
        RequestContext.replace_request(handler_input, attrs)
        DialogStateManager.clear(handler_input, "feedback", "report_decision")
        response = await handler_input.redispatch()
        speech = (response or {}).get("outputSpeech")
        if isinstance(speech, dict) and isinstance(speech.get("ssml"), str):
            speech["ssml"] = speech["ssml"].replace(
                "<speak>", "<speak>Thanks for the feedback. ", 1
            )
        return response
