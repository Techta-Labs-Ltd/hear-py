# Hear Py – DynamoDB Store Cleanup Plan

**Scope:** remove the garbage fields identified in the store audit (dead keys,
duplicate identity data, session-state leaks, content payload bloat) from the
single DynamoDB item per user.

**Output:** plan only — no code in this document.

---

## 1. Goal

Shrink the persisted item from ~110 flat fields (tens of KB, rewritten on every
request) to a small, typed set of ~30 fields (single-digit KB) without changing
user-visible behaviour.

Rules:

1. A field is persisted only if it is **read after a later request or session**.
2. Anything derived from another field is not persisted.
3. Dialog/confirmation state persists **only inside `activeDialog`** (TTL 10 min)
   — the existing authoritative mechanism (`src/services/dialog_state.py`).
4. Content belongs to the backend; we persist IDs and spoken titles only.

---

## 2. Field-by-field actions

### 2.1 Delete entirely (never read anywhere)

| Field | Note |
|---|---|
| `_announcedInSession` | dead |
| `lastPlayContentId` | superseded by `activePlayback.contentId` |
| `lastPlayStartedAt` | superseded by `activePlayback.startedAt` |
| `listPosition` | list mode unused |
| `pendingCityCapture` | superseded by `onboardingStage` |
| `pendingLocalContentRequest` | dead |
| `profilePermissionRequested` | dead |
| `showHomeBrowseOnNextLaunch` | dead |
| `suppressNextStartedEvent` | dead |
| `suppressNextStoppedEvent` | dead |
| `familyName` | never read |
| `givenName` | duplicates `userName` |
| `fullName` | duplicates `userName` |
| `deviceId` | sync-profile only; use envelope at sync time |

### 2.2 Collapse duplicates (one owner per piece of data)

| Action | Fields |
|---|---|
| Keep one name | `userName` (drop `givenName`, `fullName`, `familyName`) |
| Keep one address set | `userCity`, `userState`, `userCountry`, `userAddress` (only those read by `search_filters.py`) |
| Keep one playback cursor | `activePlayback` = `{contentId, token, offsetMs, listenedMs, status, queueId, queueIndex, startedAt, updatedAt}` — drop `audioUrl`, `title` payloads, `sessionId` |
| Drop per-turn mirrors | `currentContentId`, `currentContentTitle`, `currentCreator`, `currentCreatorId`, `currentCategory`, `currentAudioUrl`, `currentDurationSecs`, `currentPlaybackSpeeds` — all derivable from `activePlayback`/queue |
| Drop offset mirror | `lastOffsetMs`, `lastToken` — reads migrate to `activePlayback.offsetMs` / `.token` (keep a one-release read alias if needed) |
| Drop queue mirrors | `preparedNextContent`, `listModeActive`, `listPosition` |

### 2.3 Move to session attributes (never persisted)

Session-scoped flags that only the current Alexa session reads:

| Field | Note |
|---|---|
| `browseCatalog` | browse flow is within-session; relaunch refreshes from backend (`HEAR_REFRESH_BROWSE_ON_LAUNCH`) |
| `browseQueueItems`, `pendingBrowseItems` | clones of `browseCatalog` — session-only |
| `launchBrowseIds` | derived from `browseCatalog` |
| `pendingDiscoveryIntent`, `pendingDiscoveryCategory` | derived from `browseCatalog` |
| `currentSummary` | legacy, single read in `social.py:284` |
| `pendingSuggestions`, `suggestionIndex`, `excludedSuggestions`, `pendingResolution`, `pendingAmbiguity`, `awaitingSearchConfirmation` | resolution/ambiguity dialog — fold into `activeDialog` (types `search_confirmation`, `ambiguity`) |
| `awaitingReportDecision`, `reportContext` | fold into `activeDialog` type `report_decision` (dialog_state already maps it) |
| `awaitingContinueAfterFlag`, `awaitingCommunityPlayback`, `awaitingLocationConfirm`, `pendingLocationConfirm` | fold into `activeDialog` context or session attributes |
| `awaitingResume` | fold into `activeDialog` type `resume` (already supported) |
| `feedbackCandidates`, `answeredFeedbackKeys` | feedback turn state — session-only |
| `feedbackReminderAlertToken`, `feedbackAskedForToken` | collapse into `pendingFeedback` |

### 2.4 Slim what stays

| Field | Slim to |
|---|---|
| `pendingFeedback` | `{contentId, creatorId, title, askedAt}` + `awaitingFeedback` flag folded into `activeDialog` |
| `feedbackAskedTokens` / `feedbackGivenTokens` | capped at 20 each (from 50), only `str` tokens |
| `playHistory` | ID-only entries `{id}` (drop `audioUrl`, `title`, `summary`, `tracks`); cap 20 |
| `playbackQueue` | `{queueId, source, publicationId, orderedContentIds, currentIndex, createdAt}` — no titles |
| `listeningPattern` | cap keys at 40 |
| `followedCreators` | keep `{id, name}`, cap 50 |
| `locality`, `latitude`, `longitude`, `localityResolvedAt`, `locationSource`, `devicePostalCode`, `deviceCountryCode` | keep — genuinely cross-session |
| `onboardingComplete`, `onboardingStage`, `onboardingRetries`, `onboardingTownAttempts`, `onboardingTownResolverFailures`, `lastCompletedSource`, `pendingLatestSource`, `lastLatestSourceOfferContentId`, `listenerProfileResolvedAt`, `listenerProfileSkipUntil`, `launchCount`, `firstLaunchedAt`, `lastLaunchedAt` | keep — cross-session onboarding/listener state |
| `activeDialog` | keep as the **only** dialog container; every dialog read goes through `active_dialog_from_store` |

### 2.5 Stop persisting identity as state

`src/middleware/identity.py:22` writes `alexaUserId` into the store on every
request — but it is already the DynamoDB key (`id`). Stop persisting it; all
reads use `get_user_id(handler_input)` from the envelope (verify no handler
reads `store["alexaUserId"]` before removal).

---

## 3. File change plan

| File | Change |
|---|---|
| `src/services/storage/store.py` | Replace `DEFAULT_STORE` with the reduced ~30-field set (2.1–2.5). Every removed key must be confirmed unreferenced (`rg`) before deletion |
| `src/services/storage/persistence.py` | `merge_initial_store`: drop legacy removed keys on load (log count once per user); `build_persisted_snapshot`: strip any removed key before write; caps for feedback tokens / history / listening pattern |
| `src/services/dialog_state.py` | `activeDialog` becomes the sole dialog state; `_LEGACY_FLAGS` mirroring is removed after migration window; legacy reads fall back via `active_dialog_from_store` |
| `src/handlers/intents/system.py`, `play.py`, `launch.py`, `onboarding.py`, `social.py`, `src/nlp/dispatch_handler.py`, `src/handlers/feedback/*` | Replace flat-flag reads/writes with `get_active_dialog` / `activate_dialog`; browse payloads to session attributes |
| `src/middleware/identity.py` | Stop `update_store(..., {"alexaUserId": ...})` |
| `src/services/listeners.py` | Build sync profile from envelope + reduced store only |
| `config/__init__.py` | Add caps as settings: `HEAR_HISTORY_LIMIT`, `HEAR_FEEDBACK_TOKEN_CAP`, `HEAR_PATTERN_CAP`, `HEAR_FOLLOW_CAP` |
| `src/adapters/dynamodb_persistence.py` | After cleanup: emit `itemBytes` per save; alarm > 64 KB (ties into main plan section 6) |

Do 2.1+2.5 (pure removal) in one commit, 2.2+2.4 (collapse) in a second, 2.3
(session migration) in a third. Never mix with behaviour changes.

---

## 4. Migration of existing DynamoDB items

No backfill table required — removal is additive-safe because every deleted key
is one nothing reads:

1. Old items still contain the old keys after deploy. `merge_initial_store`
   drops them on load (read-through pruning); the next save rewrites a clean item.
2. Deploy with a temporary `storePruned` counter logged at INFO (aggregate only,
   no user IDs) so we can confirm all active users are pruned.
3. One-off read: sample 100 items before/after and record `itemBytes` median/p95
   to prove the shrink (target < 16 KB typical).
4. No rollback hazard: old code simply re-reads `{...}` defaults for removed
   keys, so rollback is safe as long as nothing writes removed keys while the
   flag is off — keep the pruning list versioned in one module.

---

## 5. Tests

| Test | What it proves |
|---|---|
| `test_store_pruning.py` | A store containing every removed key saves an item without any of them; `merge_initial_store` drops them on load |
| Item-size test | Building a realistic 14-launch store (from the sample item) yields < 16 KB after pruning |
| Dialog migration | `activeDialog` types `search_confirmation`, `ambiguity`, `report_decision`, `resume`, `feedback` survive save→load round-trips; legacy flat flags still map for old items |
| Session-only test | `browseCatalog`, `pendingSuggestions`, `excludedSuggestions`, `suppressNext*` never appear in `build_persisted_snapshot` output |
| Cap tests | feedback tokens / history / pattern / follows capped at configured limits |
| Identity test | `alexaUserId` is not written to the persisted store; reads still work from the envelope |

Update existing fixtures: any test that builds `{**DEFAULT_STORE, ...}` keeps
working because `DEFAULT_STORE` shrinks; tests that assert specific removed
fields exist must be changed to assert their absence.

---

## 6. Rollout

1. Dark deploy (removal commit) behind no flag — pure dead-key removal.
2. Measure `itemBytes` median/p95 on staging.
3. Collapse commit + dialog consolidation on 5% of users (flag `HEAR_DIALOG_V2=1`
   if mirroring is kept for one release), then 100%.
4. Session migration commit — browse payloads stop persisting.
5. After one release window: delete `_LEGACY_FLAGS` mirroring and the one-release
   read aliases (`lastToken`, `lastOffsetMs`).
6. Verify no `rg "browseCatalog|pendingAmbiguity|reportContext|awaitingResume"` hits in `src/`.

---

## 7. Definition of done

- [ ] `DEFAULT_STORE` reduced from ~110 to ~30 fields, each with a documented owner
- [ ] All dialog state lives in `activeDialog`; zero flat `awaiting*`/`pending*` writes
- [ ] Browse, suggestion, and feedback-turn state never persisted
- [ ] `playHistory` and `playbackQueue` contain IDs only
- [ ] `alexaUserId` not duplicated in the item
- [ ] `itemBytes` metric live; median item < 16 KB; > 64 KB alarms
- [ ] `merge_initial_store` prunes legacy keys with logged counters
- [ ] audit_project.py, compileall, and pytest all pass
