# Hear Py – Scalability, Identity & Reliability Plan (v2)

**Repo:** `hear-py` (Alexa skill backend, Python, container Lambda)
**Basis:** code on disk, `main.py`, `template.yaml`, `src/`, `config/` (checked 7 Aug 2026)

---

## 1. What this repo actually is

One Alexa skill Lambda (container image) talking to three external APIs:

| System | Caller | Direction |
|---|---|---|
| Hear backend API | `src/services/api/client.py` | skill → backend (search, listeners, locality) |
| External resolver | `src/services/resolver_client.py` | skill → resolver.hear.media (utterance → entities) |
| Alexa APIs | `src/services/alexa/` | skill → Alexa (locality, reminders) |
| DynamoDB `hear-service` | `src/adapters/dynamodb_persistence.py` | skill → one state item per user |

The SQS/webhook/taxonomy/notification-worker stack was **removed** in commit
`bd4e24d` ("Use external resolver API and remove webhook stack"). Notifications
now arrive via the backend/webhook path and must **not** be re-introduced as a
DynamoDB-synced inbox inside this repo.

### Why the previous plan is being replaced

The old `hear-py-scalability-identity-reliability-plan.md` (1,886 lines) plans
infrastructure that does not exist here: SQS refresh/delivery queues, notification
DynamoDB tables, taxonomy S3 snapshots, SQLite resolvers, webhook routers, and
outbound consumers. It also describes `src/webhooks/`, `src/resolver/`,
`src/services/notifications.py`, `src/services/taxonomy_updates.py` — none of
which exist as source files (only stale `.pyc` cache entries remain).

This plan covers only what is in this repository. Keep it under ~250 lines.

---

## 2. Principles

1. **Do not re-add the removed stack.** No SQS, no notification table, no
   taxonomy pipeline in this repo. Webhook/notification concerns live in the
   backend repo.
2. **One Lambda, one job.** The skill reads state, resolves, searches, speaks,
   saves. Everything else that is not needed for the spoken response is
   deleted or delegated to the backend.
3. **Small surface.** Fewer folders, fewer settings, one schema folder.
4. **Fail loudly, degrade gracefully.** No silently swallowed persistence
   failures, no shared sentinel keys, no memory fallback in production.

---

## 3. Remove what is unnecessary

### 3.1 Stop unnecessary sync in the request path

| Location | Problem | Action |
|---|---|---|
| `src/services/listeners.py:68` `sync_listener_for_launch` | DONE: removed from `LaunchRequestHandler` (launch.py no longer imports or awaits it); the function remains available for explicit profile-change sync |
| `config/__init__.py` `HEAR_REFRESH_BROWSE_ON_LAUNCH`, `HEAR_REFRESH_BROWSE_ON_BARE_PLAY` | Refresh browse catalog on every launch/play, re-writing the same snapshots | Default off; refresh only when a browse session is active and its cache is stale |
| `src/middleware/identity.py:22` | Writes `alexaUserId` into the persisted store on every request | Do not persist identity as user state; keep it in request attributes only |
| `src/services/storage/store.py` | DONE: persists `browseCatalog`, `browseQueueItems`, `preparedNextContent` snapshots removed — `NOT_PERSISTED_FIELDS` in `src/models.py` keeps them session-only; `playHistory`/`preparedNextContent` remain for resume/feedback flows |

### 3.2 Remove dead settings and dead code

| Item | Reason |
|---|---|
| `HEAR_NLP_TABLE` (used as a DynamoDB fallback in `config/__init__.py` `dynamo_table`) | DONE: deleted from `config/__init__.py` and `.env.example`; `dynamo_table` now only `HEAR_DDB_TABLE` |
| `DYNAMO_PLAYBACK_STATE_TABLE` | DONE: deleted from `config/__init__.py`; `src/services/storage/playback_state.py` now resolves table only from its own argument |
| `S3_PERSISTENCE_BUCKET`, `S3_PERSISTENCE_USE_LOCAL` in `.env.example` | DONE: deleted from `.env.example` |
| `NODE_ENV` in `template.yaml` + settings | Not a Node project |
| `src/services/tasks.py` `run_background` / `ensure_future` | PARTIAL: launch no longer defers `flushPreviousTrack` via `run_background` (flush is awaited with try/except); `tasks.py` remains only for telemetry and is not used for critical state |
| `src/services/feedback/`, `queue/` feature subfolders | Fold into the flat layout (section 5) |
| Stale `__pycache__/*.pyc` for deleted modules (`notifications`, `outbound_dispatch`, `proactive_notifications`, `taxonomy_updates`, `semantic_routing`, `settings`, `webhook_signing`, `middleware/notification`) | Delete with the next code pass; verify no imports remain |
| Deleted docs/skills (`docs/backend-identity.md`, `AGENTS.md`, `.agents/skills/hear-alexa-onboarding/`) | Confirm deletions are committed (currently staged); remove empty `docs/` folder |
| `utterances.md` | Keep only if it matches the current `en-GB.json`; otherwise delete or update |

Exit criteria: `rg -i "nlp_table|playback_state_table|s3_persistence|run_background|webhook_signing|outbound_dispatch|proactive_notifications|taxonomy_updates" .` returns nothing in source.

---

## 4. All schemas in one folder

Create `schemas/` at the repository root. Every payload contract currently
scattered in code and config moves here as JSON Schema:

| Schema file | Current owner | Status |
|---|---|---|
| `schemas/store.schema.json` | `src/services/storage/store.py` `DEFAULT_STORE` | CREATED (6 files, 7 Aug 2026) — matches `PERSISTED_FIELDS` in `src/models.py` |
| `schemas/resolver-request.schema.json` | `src/services/resolver_client.py` | CREATED |
| `schemas/resolver-response.schema.json` | `src/services/resolver_client.py` | CREATED — matches `ResolverResult`/`ResolvedEntity` in `src/models.py` |
| `schemas/search-request.schema.json` | `src/services/api/client.py` `search()` | CREATED |
| `schemas/search-response.schema.json` | `src/services/api/client.py` `_normalize_search_response` | CREATED |
| `schemas/listener-sync.schema.json` | `src/services/listeners.py` | CREATED |
| `schemas/playback-event.schema.json` | `src/services/playback/` | PENDING |

Rules:

- Runtime code imports one schema loader from `schemas/` (or validates via a
  single helper); no inline dict-of-fields duplicates.
- `en-GB.json` (interaction model) stays at the repo root — it is the Alexa
  deployment artifact, not an internal schema.
- Every schema change updates code, tests, and schema together.
- `DEFAULT_STORE` shrinks to fields that are genuinely persisted; everything
  else is session attributes or request attributes.

---

## 5. Flatten the folder structure

Current depth is the problem: `src/services/playback/`, `src/services/storage/`,
`src/handlers/intents/`, `src/handlers/audio/`, `src/handlers/feedback/`,
`src/adapters/`, `src/nlp/`. Target: one level under `src/`.

```text
main.py
config/__init__.py                 # settings only
schemas/                           # all JSON Schema contracts (section 4)
src/
  application.py                   # composition root (unchanged role)
  runtime.py                       # was src/runtime/__init__.py
  registry.py                      # handler + middleware registration
  handlers.py                      # was src/handlers/ (flat, feature files)
  middleware.py                    # was src/middleware/ (flat, already shallow)
  services/
    api.py                         # Hear backend client (was services/api/)
    alexa.py                       # was services/alexa/
    resolver.py                    # was services/resolver_client.py
    listeners.py
    feedback.py                    # was services/feedback/
    playback.py                    # was services/playback/
    queue.py                       # was services/queue/
    persistence.py                 # was services/storage/ + adapters/ merged
    store.py
  utils/                           # pure helpers only (keep)
tests/                             # mirrors src/ structure
```

Rationale:

- One feature = one file (≤ ~400 lines each; split only when exceeded).
- Persistence adapter and storage service become one ownership boundary
  (`services/persistence.py`), so DynamoDB vs memory choice lives next to the
  state shape.
- `nlp/` (dispatch + patterns) merges into `handlers.py`/`registry.py`; the
  NLP/interceptor double-dispatch is removed so there is exactly one routing
  mechanism.
- Delete `src/adapters/` and `docs/` as folders.

Migration is mechanical (import renames) and must be done in one commit so the
tree and `PROJECT_MAP.txt` stay in sync. Do not reorganise and refactor
behaviour in the same commit.

---

## 6. DynamoDB persistence — keep, but bound it

Do **not** rebuild into a multi-item single-table design now. The skill writes
one item per user and the backend is the real store of record. Make the current
design correct and bounded:

| Fix | Location | Detail |
|---|---|---|
| Remove sentinel keys | `src/adapters/persistence_user_id.py` | `__invalid_envelope__`, `session:<id>`, `__no_identity__` must never reach DynamoDB. Missing user ID → skip persistence and log/deny, never write a shared key |
| Projected, smaller item | `build_persisted_snapshot` in `src/services/storage/persistence.py:633` | Currently only strips 2 transient fields. Strip browse catalog payloads, summaries, full history entries, queue item payloads per section 3.1 |
| Measure item size | adapter save path | Log/emit `itemBytes` before every write; alarm > 64 KB |
| Surface failures | `LoadPersistenceInterceptor` / `SavePersistenceInterceptor` (`persistence.py:643-701`) | Both swallow exceptions with `pass`. Log + metric on failure; for state-critical actions return a spoken recovery message instead of silently using empty state |
| Fail closed in production | `src/application.py:28` | `ENV=production` (or Lambda) with no `HEAR_DDB_TABLE` must raise at cold start, not fall back to memory |
| Drop `HEAR_NLP_TABLE` fallback | `config/__init__.py` `dynamo_table` | Delete the fallback chain |

Keep: conditional versioned write (`stateVersion`), strong reads for
foreground dialog state, TTL.

---

## 7. Identity — one minimal, honest model

`alexaUserId` stays the persistence key for now (acceptable for this single
Lambda), but stop pretending it is a Hear account:

1. Never log or persist raw provider IDs beyond the DDB key — log an HMAC/hash.
2. Send `alexaUserId` to backend/resolver only where the backend expects it;
   stop persisting it in the store (`src/middleware/identity.py`).
3. Build one `IdentityContext` (request attributes only):
   `alexa_user_id`, `person_id`, `device_id`, `access_token`, `is_linked`.
   Middleware computes it once; services read it, nothing else re-derives it.
4. When account linking is introduced, the linked Hear `sub` becomes the
   persistence key — design `IdentityContext` now so the swap is local to
   `persistence_user_id.py`.
5. Never merge users by email/name/location (old `docs/backend-identity.md`
   design is deleted and stays deleted).

---

## 8. Reliability fixes

| Fix | Location |
|---|---|
| Reuse one `httpx.AsyncClient` per process (lazy init, loop-safe) | `src/services/api/client.py:28`, `src/services/resolver_client.py:234` — both construct a client per call today |
| Unified typed error policy (timeout / rate-limited / auth / 5xx / permanent) | both clients; stop collapsing every failure to `(0, None)` |
| Propagate remaining Lambda deadline into every HTTP call; never retry past it | `src/middleware/deadline.py` + clients |
| No critical work via `asyncio.ensure_future` | `src/services/tasks.py` (delete or restrict to telemetry) |
| Remove per-invocation `asyncio.run` strategy risk | `main.py:20` — keep it only if tests prove cleanup is safe; otherwise use one module-level loop/thread strategy; document the choice |
| Stop swallowing handler/interceptor errors | `src/runtime/__init__.py` — log + metric every suppressed error |
| Privacy: remove full search-body logging | DONE: `src/services/api/client.py:150` now logs path + query length/hash + filter keys only |
| No raw utterances/tokens/addresses in logs | audit all `logger.info/warning` calls |
| DynamoDB reads/writes off the event loop | DONE: `DynamoTable` (`src/adapters/dynamodb.py`) methods are now async and wrap boto3 in `asyncio.to_thread`; `DynamoDbPersistenceAdapter` awaits them (was awaiting sync methods — a TypeError in production) |
| Production fail-closed persistence | DONE: `build_persistence_adapter()` in `src/application.py` raises if `HEAR_DDB_TABLE` is unset in staging/production |

---

## 9. Verification gate

Run before calling this plan done:

```powershell
python .agents/skills/hear-alexa-python/scripts/audit_project.py .
python -m compileall -q main.py src config
python -m pytest -q
rg -i "nlp_table|playback_state_table|s3_persistence|run_background|webhook|outbound_dispatch|proactive_notifications|taxonomy_updates" src config main.py template.yaml
```

---

## 10. Execution order

1. **Phase A – Removal (1 commit):** delete dead settings, dead code,
   `tasks.py` background manager, foreground listener sync, store snapshots,
   stale `.pyc`, `docs/`. No behaviour change beyond removal.
   **STATUS:** in progress — settings removed (`HEAR_NLP_TABLE`,
   `DYNAMO_PLAYBACK_STATE_TABLE`, S3 vars), listener sync removed from launch,
   `run_background` removed from launch flush, dead docs staged for deletion.
2. **Phase B – Schemas + layout (1 commit):** create `schemas/`, flatten
   `src/`, merge `adapters/` into `services/persistence.py`, single routing
   mechanism. Mechanical renames only.
3. **Phase C – Persistence hardening:** sentinel removal, item size metric,
   failure visibility, production fail-closed.
4. **Phase D – Clients + privacy:** pooled clients, typed errors, deadline
   propagation, redacted logging.
5. **Phase E – Identity:** `IdentityContext`, hashed provider IDs in logs.

## 11. Definition of done

- [ ] No SQS/webhook/taxonomy/notification-table code or settings remain
- [ ] Foreground launch performs no listener sync and no browse refresh by default
- [ ] Persisted item is small (< 16 KB typical), measured, and alerted > 64 KB
- [ ] No `__no_identity__` / `session:` / `__invalid_envelope__` keys ever written
- [ ] Persistence failures are logged, metriced, and spoken-recoverable
- [ ] Production cannot fall back to memory persistence
- [ ] All contracts live in `schemas/`; `DEFAULT_STORE` matches `store.schema.json`
- [ ] `src/` is at most one folder deep; `PROJECT_MAP.txt` matches the tree
- [ ] One shared HTTP client per process; typed errors; deadlines enforced
- [ ] No raw utterances, tokens, addresses, or provider IDs in logs
- [ ] `audit_project.py`, `compileall`, and `pytest` all pass
