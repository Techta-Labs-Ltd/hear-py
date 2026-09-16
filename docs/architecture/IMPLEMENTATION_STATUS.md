# Architecture and reliability implementation status

Baseline: `6e138e2cb5a095c4cc0a856291430cf6a3b683fb` on `develop`.
Implementation branch: `refactor/develop-architecture-reliability`.
Date: 15 September 2026.

This is the first staged reliability update. It does **not** complete the comprehensive refactor. The implementation follows the specification's allowance for an independently reviewable foundation release before the feature migration and deployed outbox stage. Requirements below describe specific behaviours, not wholesale completion of a file or feature.

## Source findings

| Requirement | Status | Evidence and remaining work |
| --- | --- | --- |
| A01: explicit composition and dependency injection | OPEN — IMPLEMENT | `ApplicationContainer` now has an explicit typed constructor and `RouteRegistry` no longer uses reflection to construct handlers. Whole-container feature dependencies and request factories remain to be removed. |
| A02: inject actions into play controllers | FIXED — DO NOT MODIFY | Play controllers require injected actions, and `RouteRegistry` is their sole production construction site. No `deps` fallback remains in either controller. |
| A03: typed feature inputs and outcomes | OPEN — IMPLEMENT | Models still parse Alexa input and produce platform responses. Full feature migration is required. |
| A04: request-owned User and RequestContext contracts | OPEN — IMPLEMENT, with completed isolation fixes | `User.snapshot`, update inputs/results, defaults and memory storage now copy nested values. Typed commit results/receipts belong to User. Feature operations still receive `handler_input`; their framework-independent gateway remains open. |
| A05: application versus request lifetimes | EXISTING — PRESERVE; request graph OPEN | The runtime continues to create a fresh envelope, attribute manager, deadline and response builder per invocation. The application container and feature graph remain cached; explicit request factories are not implemented. |
| A06: configured Hear/Resolver pool isolation | FIXED — DO NOT MODIFY | `HttpPool` captures URL/authentication at construction. `get()` takes no configuration. Hear, Resolver and notification clients reject incompatible injected pools. A bound client rejects another upstream before sending credentials. Closed clients are replaced and closed-loop entries are not reused. See `test_http_pool_isolation.py`. Platform clients which intentionally use multiple Amazon endpoints still need their own upstream/circuit review. |
| A07: personalized resolver cache leakage | FIXED — DO NOT MODIFY | Either listener ID or Alexa user ID disables shared caching. Anonymous cache entries are copied on insert/read, and only resolved results are cached. Existing anonymous cache coverage and new isolation cases pass. |
| A08: save failures returning prepared success | FIXED — DO NOT MODIFY for runtime commit failures | Required save failures propagate into exception handling; prepared directives and speech are discarded. Runtime exceptions skip commit interceptors. Playback/dialogue state changes and existing reliable-save markers require successful commits. All models must still adopt explicit failure outcomes: a model which catches its own error is not yet distinguishable from success by this runtime. |
| A09: unsafe persistence configuration | FIXED — DO NOT MODIFY | Unknown drivers fail. Memory persistence or a missing durable table fails in staging, production and Lambda. Local development retains memory support. |
| A10: silently acknowledged invalid SQS records | FIXED — DO NOT MODIFY | The outbound consumer validates JSON, v3 envelope/data fields and timestamps. Malformed and failed records become partial failures; missing identifiers fail the batch. Both workers preserve remaining Lambda time. Notification delivery is retried/redriven if a required backend status cannot be recorded. |
| A11: follow/report occurrence IDs | VERIFY — CONTRACT/REGRESSION | Existing wire IDs remain unchanged. Backend deduplication semantics were not verified, so new occurrence IDs have not been guessed. |
| A12: actual coupled DynamoDB transactions | OPEN — IMPLEMENT | Scope writes still use independent operations. Receipts report versions only after confirmed success, but this does not make multi-scope writes atomic. W09 must introduce and test transactions. |

## Work packages

| Package | Status | Delivered or remaining scope |
| --- | --- | --- |
| W00 | Completed for this stage | Pinned checkout, baseline tests, route/entrypoint preservation, consumer inventory and file ledger. |
| W01 | Partial | Deployed durability guards and bounded request/worker deadlines are implemented. Full startup option validation and minimal worker composition are open. |
| W02 | Open | Explicit constructor injection and application/request/record graph factories. |
| W03 | Partial | State copies and commit contracts are implemented. Request-owned, framework-independent models and typed feature commands are open. |
| W04 | Partial | Commit failure propagation, callback response filtering, fresh error builders, bounded redispatch, and removal of interceptor signature introspection. Uniform asynchronous interceptor contracts, typed action failures and all lifecycle gates remain open. |
| W05 | Partial | Configured upstream isolation, resolver cache protection and resolver log redaction. Listener-bound client identities, the complete filter policy and full transport/status/retry classification remain open. |
| W06 | Open | Search → availability → play migration. Existing flow tests remain intact. |
| W07 | Open | Playback/feedback/dialogue model migration and all duplicate/stale-event guarantees. |
| W08 | Partial | Worker envelope validation, partial failures, delivery acknowledgement checks and deadlines. Feature constructor/model migration remains open. |
| W09 | Partial | Fresh defaults, immutable snapshots, memory change-set merging, save receipts and bounded/lazy DynamoDB SDK construction. Transactions, corrupt/newer-version rejection and storage TTL/migration verification remain open. |
| W10 | BLOCKED — EXTERNAL for deployment; implementation OPEN | No outbox implementation or producer flag is enabled. Requires an additive deployed outbox, relay, bounded recovery, alarms and backend deduplication verification. AWS/backend deployment access was not exercised. |
| W11 | Partial | Obsolete interceptor signature adapter and resolver diagnostic value copier removed; pure state normalization moved into the existing utility owner. Full dependency audit strengthening, type checking and application-wide dead-code cleanup remain open. |

## Preserved behaviour

- The physical key format, schema version 2, four scopes, field classifications, and non-persisted identity/profile fields are unchanged.
- Alias-to-canonical hydration and the no-save-after-unavailable-load protection retain regression coverage.
- Existing publication-first availability, ordered publication tracks, lazy queue navigation, feedback origins, named source speech, slot resolution and UK prompts remain covered by the existing suite.
- The 58 registered handlers, route order, three Lambda entrypoints and resolver diagnostic remain available.
- Reminder functionality remains removed. No endpoint, table, queue, permission or deployment workflow was removed or replaced.

## Verification

Tests used Python 3.12 and the repository's `.env.example` as the local `.env`, matching CI setup. Commands run from the repository root:

| Command/check | Result |
| --- | --- |
| Baseline `.venv/bin/python -m pytest -q` | 914 passed. |
| Baseline Ruff | One pre-existing import-format error in `src/alexa/help.py`; corrected in this update. |
| Final `.venv/bin/python -m pytest -q` | 956 passed, including 42 added cases. Entire unit suite runs with live sockets/DNS blocked and deterministic HTTP stubs. |
| `.venv/bin/python -m ruff check src tests` | Pass. |
| `.venv/bin/python -m compileall -q main.py src config` | Pass. |
| Application build smoke check | Skill builds with 58 registered handlers. |
| Local template/contract inspection | CloudFormation YAML parses; both SQS event mappings retain `ReportBatchItemFailures` and redrive queues; JSON schemas and interaction model parse. |
| `git diff --check` | Pass. |
| AWS deployment, DynamoDB integration, real Alexa device testing | Not performed. |

Automatic approval review blocked an earlier full test attempt because fixtures attempted live API calls. The suite now uses a deterministic unavailable-dependency transport unless a test provides its own transport. Socket/DNS guards cover collection and execution; unexpected low-level egress fails the test. The final passing run did not require permission to send fixture identities or tokens externally.

## Compatibility and remaining risks

No wire fields or stored schema version changed. Stricter worker validation intentionally sends malformed or unsupported envelopes through existing SQS retries/redrive instead of acknowledging them. Existing v3 producer envelopes remain supported.

An essential write timeout is an **uncertain remote outcome**, not proof that DynamoDB rolled back. Independent scope operations can still partially commit. Local state and SQS publication are still separate writes. Neither an atomic state/event guarantee nor exactly-once delivery is claimed; those remain W09/W10 work.

Source-level pool cleanup is covered for the current loop and closed-client replacement. Full application shutdown across managed loops still needs an explicit lifecycle integration.

Live Hear/Resolver OpenAPI retrieval was unavailable during this task. Checked-in contracts and callers informed this stage. There is no evidence permitting removal of `listeners/register` or `listeners/sync`.

The rollback code baseline is the pinned develop commit above; this stage preserves its physical state format. Production rollback and mixed-version integration have not been exercised.

See [API_CONSUMER_MAP.md](API_CONSUMER_MAP.md) and [FILE_LEDGER.md](FILE_LEDGER.md) for scope and file evidence. The supplied full specification is retained as [COMPREHENSIVE_REFACTOR_SPEC.md](COMPREHENSIVE_REFACTOR_SPEC.md).
