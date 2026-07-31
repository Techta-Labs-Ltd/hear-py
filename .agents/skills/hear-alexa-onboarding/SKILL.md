---
name: hear-alexa-onboarding
description: Build, review, debug, and verify the Hear Alexa skill onboarding flow in this repository. Use for the new-user gate, permission consent and card handling, Amazon API city detection (geolocation/device address), manual town capture, town confirmation, listener backend sync, the local-community follow-up prompt, and returning-user welcomes; also use to flag broken onboarding stage order, dead onboarding state, permission wiring gaps, and missing Connections.Response handling.
---

# Hear Alexa Onboarding

## The onboarding checklist

Every onboarding change must keep this checklist intact:

1. **New-user detection.** The gate (`OnboardingGateHandler` in `src/middleware/onboarding_gate.py`) routes users with no `onboardingComplete`, `playCount == 0`, and no `lastToken` through onboarding before any content handler. `_is_new_user()` must stay the single definition of a new user.
2. **Registered-user + Amazon API city detection.** Check the user is known and, when device permissions are granted, detect the city from the Amazon API before asking. The primitives live in `src/services/alexa/locality.py` (`has_permission`, `get_geolocation`, `get_device_address`) and the scopes in `config/permission_scopes.py`. If the user declines permission, fall back to manual town entry (`handle_permission_no`, stage `ask_town`, speaking `ONBOARDING_LOCATION_DENIED`). If permission is granted but the API returns no location, fall back via `handle_location_not_found` (stage `ask_town`, speaking `LOCATION_NOT_FOUND`), NOT `handle_permission_no`.
3. **Permission ask.** `LaunchRequest` for a new user always starts with `ask_for_permission` (stage `ask_permission`, speaking `ONBOARDING_ASK_PERMISSION` "Welcome to Hear. I can bring you the latest audio from your local community... Would that be alright?"). Yes checks if scopes are granted to auto-detect location or sends an `AskForPermissionsConsent` card for DEVICE_ADDRESS + GEOLOCATION; no falls back to manual town entry (`ONBOARDING_LOCATION_DENIED`, stage `ask_town`).
4. **Manual town capture.** `TownCaptureHandler`/`SetLocationHandler` (stage `ask_town`) route the spoken town through `resolve_utterance("resolve_location", ..., alexa_intent="TownCaptureIntent")`. A match stages `pendingLocationConfirm`/`awaitingLocationConfirm` (stage `await_location_confirm`) and asks `ONBOARDING_TOWN_CONFIRM`; candidates produce a "Did you mean ..." prompt; a miss retries up to `MAX_TOWN_ATTEMPTS` (3) then `finalize_town_skipped`.
5. **Confirmation + backend sync.** Yes (`YesIntentHandler._confirm_location`) persists `userCity`/`locality`/`deviceCountryCode`/`latitude`/`longitude`, sets `onboardingComplete: True`, clears the stage, and awaits `sync_listener` with the confirmed profile. No (`NoIntentHandler`) clears the pending town and asks for a different one.
6. **Local-community follow-up prompt.** After the location is confirmed the skill should ask whether the user wants to listen to content from their local community (`awaitingCommunityPlayback`). See known gap G1 in `references/onboarding-flow.md`.

## Establish the source of truth

1. Read `README.md`, the files being changed, their registries or exports, and the closest tests.
2. Read [references/onboarding-flow.md](references/onboarding-flow.md) before touching any stage, store key, speech constant, or handler in the flow.
3. Treat executable code, tests, and `README.md` as the architectural source of truth. Search before writing:

```powershell
rg "onboarding|TownCapture|SetLocation|awaitingLocation|awaitingCommunityPlayback|resolve_location" src tests en-GB.json
rg "get_geolocation|get_device_address|Connections.Response|ASK_FOR_PERMISSIONS" src
```

Reuse or extend the existing owner. Never add a second implementation of the same responsibility.

## Implement in the established shape

- Keep the gate in `src/middleware/onboarding_gate.py` and register it only through `src/middleware/pipeline.py` (`GATE_HANDLERS`, before `TownCaptureHandler` and `IntentDispatchHandler`).
- Keep onboarding flow functions in `src/handlers/intents/onboarding.py`; keep `LaunchRequestHandler`/`TownCaptureHandler`/`SetLocationHandler` in `src/handlers/intents/launch.py`.
- Stage strings must come from the canonical set: `ask_permission`, `ask_town`, `await_location_confirm`, `confirm_town_for_community` (`ONBOARDING_ASK_TOWN` in `onboarding.py`; `confirm_town_for_community` is referenced by `launch.py`, `play.py`, `system.py`).
- Persist only through `get_store`/`update_store`; every onboarding store key must exist in `DEFAULT_STORE` (`src/services/storage/store.py`).
- Resolve towns only through `resolve_utterance("resolve_location", ..., alexa_intent="TownCaptureIntent")` from `src/services/resolver_client.py`; handle `ResolverUnavailable` with the retry prompt.
- Sync the confirmed listener to the backend only via `sync_listener` inside `_confirm_location`.
- Reuse speech constants from `src/utils/speech.py`; never embed prompt text in handlers.
- Update `en-GB.json`, NLP routing (`src/nlp/__init__.py` town-capture ownership), dispatch (`src/nlp/dispatch_handler.py`), exports, and tests together.

## Execute changes

1. Trace the request from `main.py` through `src/middleware/pipeline.py`, `NlpInterceptor`, the gate, the town handlers, `_confirm_location`, and the persistence save.
2. Identify the files and contracts that must change.
3. Make the smallest cohesive edit and preserve unrelated changes.
4. Run:

```powershell
python .agents/skills/hear-alexa-onboarding/scripts/audit_onboarding.py .
python -m compileall -q main.py src config
python -m pytest tests/test_onboarding_simulation.py -q
python -m pytest -q
```

If Python is blocked by the sandbox, retry with required execution approval. Never claim verification unless the commands ran.

## Flag incorrect implementations

For review-only requests, report findings without editing. Give file and line, violated contract, runtime impact, and preferred owner/pattern.

Block completion for:

- duplicate onboarding functions or handlers, or double registration of the gate;
- gate registered after content handlers or outside `GATE_HANDLERS`;
- stage strings outside the canonical set, or store keys missing from `DEFAULT_STORE`;
- town resolution that bypasses `resolve_utterance("resolve_location", ...)` or misses the `alexa_intent="TownCaptureIntent"` contract;
- confirmation that persists the city without awaiting `sync_listener`;
- permission scopes embedded in feature code instead of `config/permission_scopes.py`;
- changing the known gaps in `references/onboarding-flow.md` without removing them from the report too;
- tests that mock away the behavior they claim to prove.

Separate pre-existing findings (the known gaps) from regressions. Do not silently clean unrelated code.

## Completion gate

Confirm the stage machine is intact (no new stages, no skipped transitions), `_is_new_user` is unchanged, town capture still resolves through the resolver and confirms before persisting, `sync_listener` runs on confirm, the gate order in `pipeline.py` is preserved, model and Python routing agree, and audit/compilation/simulation/full tests pass or exact failures are reported.
