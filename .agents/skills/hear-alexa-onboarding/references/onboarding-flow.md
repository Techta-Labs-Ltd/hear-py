# Hear Onboarding Flow Reference

Anchors are `src/...` relative to the repo root. Line numbers were current at the time of writing; re-grep if a file drifts.

## Stage machine

| Stage | Set by | Cleared by | Gate behavior |
|---|---|---|---|
| `ask_permission` | `ask_for_permission` (`handlers/intents/onboarding.py:27`), `handle_permission_yes` (`onboarding.py:42`) | `handle_permission_no` (`onboarding.py:53`) → `ask_town` | `OnboardingGateHandler` owns Yes/No here (`middleware/onboarding_gate.py:69`) |
| `ask_town` (`ONBOARDING_ASK_TOWN`, `onboarding.py:21`) | `handle_permission_no` (`onboarding.py:56`), `start_town_capture` (`onboarding.py:91`), `resume_town_capture` path, `launch.py:120`, `launch.py:347` | `stage_town_confirmation` → `await_location_confirm` (`onboarding.py:148`); `finalize_town_skipped` → `None` + `onboardingComplete: True` (`onboarding.py:203`) | `TownCaptureHandler.can_handle` requires this stage (`launch.py:283`); `NlpInterceptor` owns any raw utterance here (`nlp/__init__.py:161`) |
| `await_location_confirm` | `stage_town_confirmation` (`onboarding.py:148`), `auto_detect_location_or_manual` (`onboarding.py:220`) | `YesIntentHandler._confirm_location` (`system.py:243`) → `None` + `onboardingComplete`; `NoIntentHandler` → `None` (`system.py:724`) | `YesIntentHandler` branch 0 (`system.py:179`) |
| `confirm_town_for_community` | `PlayContentHandler`/`BrowseContentHandler` when a community request arrives with no location (`handlers/intents/play.py:617,923`) | `LaunchRequestHandler` → `start_town_capture` (`launch.py:120`) | not `ask_town`, so `TownCaptureHandler.can_handle` is False; dispatch still routes town answers via `IntentDispatchHandler` |

Terminal state: `onboardingComplete: True`, `onboardingStage: None`, `userCity` + `locality` persisted, `awaitingLocationConfirm: False`, `pendingLocationConfirm: None`. After confirmation, `awaitingCommunityPlayback: True` and the speech appends `COMMUNITY_PLAYBACK_OFFER(city)`; the next Yes runs `_handle_community_play_yes` (`system.py:298`), the next No clears the offer (`system.py:736`). A newer search confirmation supersedes the offer (`nlp/dispatch_handler.py:_ask_search_confirmation`).

## New-user gate

- `_is_new_user(store)`: not `onboardingComplete` AND `playCount == 0` AND no `lastToken` (`middleware/onboarding_gate.py:16`).
- Registration order (`middleware/pipeline.py:17-23`): `CanFulfillIntentHandler`, `FeedbackGateHandler`, `OnboardingGateHandler`, `TownCaptureHandler`, `IntentDispatchHandler`.
- Interceptors run before gate handlers: `LambdaDeadlineInterceptor`, `LoadPersistenceInterceptor`, `NotificationMiddleware`, `NlpInterceptor`, `ConfirmationMiddleware` (`pipeline.py:25-31`).
- When DEVICE_ADDRESS or GEOLOCATION is already GRANTED, the gate skips the permission ask and runs `auto_detect_location_or_manual` (`onboarding_gate.py:_location_scopes_granted`).
- `ConnectionsResponseHandler` (`onboarding.py`) handles the consent card's in-session reply: `2xx` → auto-detect, other → `handle_permission_no`; for completed onboarding it just acks (`CONSENT_CARD_THANKS` / `LOCATION_DECLINED`). Registered first in `handlers/registry.py`.

## Resolver contract

- Town resolution: `resolve_utterance("resolve_location", phrase, alexa_intent="TownCaptureIntent")` (`onboarding.py:118,168`).
- Response shape: `{"version": 1, "status": "resolved", "resolution": {"match": {city, locality, countryCode, latitude, longitude}, "candidates": [...]}}`.
  - match → `pendingLocationConfirm = match`, `awaitingLocationConfirm = True`, speak `ONBOARDING_TOWN_CONFIRM(city)`.
  - no match + candidates → "Did you mean {c1} or {c2}?" retry (`onboarding.py:132-143`).
  - no match + no candidates → `resume_town_capture` (max `MAX_TOWN_ATTEMPTS = 3`, `onboarding.py:21`).
  - `ResolverUnavailable` → retry prompt (`onboarding.py:124-129`).
- Search intents (PlayContentIntent, PlayLocalIntent, ...) resolve via `resolve_utterance("resolve_search", raw, alexa_intent=...)` (`nlp/__init__.py:214-221`); town capture during `ask_town` never calls the resolver (`nlp/__init__.py:161-171`).

## Persistence

- `get_store` / `update_store` only (`services/storage/persistence.py`).
- Keys used by onboarding and their `DEFAULT_STORE` defaults (`services/storage/store.py`): `onboardingComplete: False`, `onboardingStage: None`, `onboardingRetries: 0`, `onboardingTownAttempts: 0`, `pendingLocationConfirm: None`, `awaitingLocationConfirm: False`, `awaitingCommunityPlayback: False`, `userCity: None`, `locality: None`, `deviceCountryCode: None`, `latitude: None`, `longitude: None`, `locationSource: None`, `localityResolvedAt`, `devicePostalCode: None`.
- Store keys read by onboarding code that are NOT in `DEFAULT_STORE`: `deviceId` (used at `system.py:279`), `userEmail`, `userName` — optional profile enrichments.

## Amazon API primitives

`src/services/alexa/locality.py`:

- `has_permission(handler_input, scope)` — scopes GRANTED check (`locality.py:52`).
- `get_geolocation(handler_input)` — latitude/longitude/accuracy from request context (`locality.py:8`).
- `get_device_address(handler_input)` — full address (incl. `city`) via `/v1/devices/{id}/settings/address`; 403 → `{"denied": True}` (`locality.py:24`).
- `detect_device_location(handler_input)` — combines the two: city from the device address, coordinates from the geolocation context; returns a match dict with `source="device"` or None (`locality.py:68`).
- `ensure_listener_profile` / `apply_listener_profile` — profile name/email fetch with TTL + backoff (`locality.py:157,251`).
- `get_missing_permissions(handler_input, store)` — DEVICE_ADDRESS / GEOLOCATION / profile scopes (`locality.py:283`).

Scopes: `config/permission_scopes.py` — `DEVICE_ADDRESS`, `GEOLOCATION_READ`, `PROFILE_*_READ`.

## Speech constants

`src/utils/speech.py`: `ONBOARDING_ASK_PERMISSION` (:654), `ONBOARDING_CONSENT_CARD_SENT` (:655), `ONBOARDING_LOCATION_DENIED` (:656), `WELCOME_FIRST_ASK_TOWN` (:122), `WELCOME_FIRST` (:134), `WELCOME_FIRST_HAS_CITY` (:127), `REPROMPT_ASK_TOWN` (:159), `TOWN_NOT_UNDERSTOOD` (:143), `TOWN_GOT_IT` (:139), `REPROMPT_CITY` (:153), `TOWN_SKIPPED` (:141), `REPROMPT_NO_CITY` (:157), `ONBOARDING_TOWN_CONFIRM` (:658), `ONBOARDING_FETCHING_LOCATION` (:657), `ONBOARDING_DETECTED_TOWN` (next to :657), `CONSENT_CARD_THANKS`, `COMMUNITY_PLAYBACK_OFFER`, `LOCATION_ASK_CITY` (:664), `LOCATION_CONFIRMED` (:666), `LOCATION_DECLINED` (:665), `LOCATION_RETRY` (:671), `COMMUNITY_NEEDS_TOWN` (:163), `WELCOME_RETURN_NAMED` (:678), `WELCOME_RETURN_CITY` (:679), `WELCOME_RETURN_GENERIC` (:680), `WELCOME_REPROMPT` (:165).

## Dispatch

- `TownCaptureIntent` → `town_capture` (`nlp/patterns.py:81`); `SetLocationIntent` → `location_set` (`nlp/patterns.py:80`).
- `NlpInterceptor` special cases: `SetLocationIntent` → `location_set` with `townName` slot (`nlp/__init__.py:73`); `TownCaptureIntent` → `town_capture` unless a `pendingAmbiguity` dialog owns the reply (`nlp/__init__.py:92`); `ask_town` stage owns all raw utterances (`nlp/__init__.py:161`).
- `IntentDispatchHandler` (`nlp/dispatch_handler.py`): `town_capture` → `TownCaptureHandler`, `location_set` → `SetLocationHandler` (dispatch bypasses `can_handle`).
- `TownCaptureHandler.can_handle` (`launch.py:279`): stage `ask_town`, no conflicting active dialog, then NLP intent `town_capture` or Alexa intents `TownCaptureIntent`/`SetLocationIntent`/`AMAZON.NoIntent`/`SkipFeedbackIntent`/`AMAZON.CancelIntent`.
- Yes/No routing during onboarding lives in `YesIntentHandler` (`system.py:160`) and `NoIntentHandler` (`system.py:700`): branch 0 `awaitingLocationConfirm`, then `awaitingCommunityPlayback`, then the search-confirmation dialog. The dead `awaitingLocationChoice` branches were removed (G3).

## Community request without location

`wants_local_community_content` (`utils/search_filters.py:289`) treats `near me|nearby|local|community|my area|...` as local. `PlayContentHandler`/`BrowseContentHandler` set stage `confirm_town_for_community` and speak `COMMUNITY_NEEDS_TOWN` (`play.py:617,923`). The town answer works in-session via `IntentDispatchHandler`. After the town is confirmed, `_confirm_location` activates `awaitingCommunityPlayback` and offers `COMMUNITY_PLAYBACK_OFFER(city)`; Yes runs `_handle_community_play_yes` (local feed), No dismisses.

## Previously documented gaps — resolved

- **G1 — Community follow-up prompt.** `_confirm_location` now sets `awaitingCommunityPlayback: True` and appends `COMMUNITY_PLAYBACK_OFFER(city)` to the confirmation speech (`system.py:260-296`). Yes → `_handle_community_play_yes`; No → existing branch. A newer search confirmation supersedes the offer (`dispatch_handler.py:_ask_search_confirmation`), and `_handle_community_play_yes` clears stale search-confirmation state.
- **G2 — Amazon API city detection.** `detect_device_location` (`locality.py`) now drives the flow after consent: called by `ConnectionsResponseHandler` and by `OnboardingGateHandler` when scopes are already GRANTED; a detected city is staged for confirmation with `source="device"` and persisted as `locationSource: "device"`; no city → manual town capture.
- **G3 — `awaitingLocationChoice` dead code.** The Yes/No branches at `system.py:166,712` were removed; the gate owns the `ask_permission` Yes/No answers. The audit now requires the key to be absent.
- **G4 — No `Connections.Response` handler.** `ConnectionsResponseHandler` (`onboarding.py`) accepts the consent card reply: `2xx` → auto-detect, else manual town; completed users get a plain ack. Relaunches with GRANTED scopes skip the permission ask entirely.
- **G5 — Town skip does not release the gate.** `finalize_town_skipped` now sets `onboardingComplete: True`, so the next intent is no longer re-gated to the permission ask.

The simulation suite (`tests/test_onboarding_simulation.py`, scenarios S1-S9) verifies all of the above and writes `tests/onboarding_simulation_report.md`; `scripts/audit_onboarding.py` asserts the structural invariants (exit 0 = no GAPs).
