# Hear-Py: Comprehensive Architecture and Reliability Fix Specification

**Repository:** Techta-Labs-Ltd/hear-py  
**Branch checked:** develop  
**Baseline commit:** 6e138e2cb5a095c4cc0a856291430cf6a3b683fb  
**Prepared:** 15 September 2026  
**Deliverable:** Implementation specification for a coding agent; not an applied patch or a test-pass report.

## 0. Instruction to the implementing agent

Refactor the existing application into readable, class-based MVC with explicit constructor injection, request-scoped listener dependencies, typed feature inputs and results, one User state gateway, correct middleware and response handling, and one filter-normalisation owner.

Implement the changes in this specification across their production callers, tests, configuration, schemas and deployment definitions. Do not stop after moving files, adding interfaces, writing documentation, or placing old functions inside classes. Finish each migrated execution path and remove its obsolete implementation.

Preserve the existing top-level structure and functioning product behaviour. Do not build a second application beside the current one. Do not create competing containers, User stores, filter builders, resolver implementations, response systems or notification stores.

Start from the actual checked-out revision. If it differs from the baseline above, reconcile its changes before editing. Preserve unrelated work. A requirement already satisfied should be marked **FIXED — DO NOT MODIFY**, with its evidence. A partially completed requirement should retain that fixed portion and identify only the remaining work.

A source review established the central problems and the module inventory used below. It did not execute the application, test suite, AWS deployment or live backend contracts. Grouped module instructions describe the migration required of those modules; they are not claims that every function in each file has been individually proven defective.

### Status vocabulary

| Status | Meaning |
|---|---|
| EXISTING — PRESERVE | This mechanism exists in the reviewed source. Preserve its behaviour while changing ownership or constructors where required. |
| OPEN — IMPLEMENT | The target architecture or demonstrated source-level issue requires a change. |
| VERIFY — CONTRACT/REGRESSION | Establish the external contract or reproduce the suspected defect before changing behaviour. |
| FIXED — DO NOT MODIFY | The implementing agent has verified the requirement is already satisfied; retain its regression coverage. |
| BLOCKED — EXTERNAL | An identified deployment or backend dependency cannot be completed with available authorised access. Name the exact blocker; continue independent work. |

A status applies to a behaviour or requirement, not automatically to every line of a file. Mechanical constructor changes can touch a file containing preserved behaviour without reopening that behaviour as a new bug.

## 1. Preserve the work that already exists

The baseline already contains `Application`, `ApplicationContainer`, `RouteRegistry`, class-based controllers, `User`, `RequestContext`, scoped DynamoDB persistence, and a central `StateSchema`. Reuse and improve them. [R1–R5]

Preserve these mechanisms:

- The four listener-state scopes: `CORE`, `PLAYBACK`, `DIALOG`, `CACHE`.
- Existing storage key derivation, canonical identity handling and guarded alias migration during the compatibility phase.
- Changed-field tracking, optimistic version checks, bounded collections and item-size protection.
- The protection that prevents saving default state after a failed or deliberately skipped persistence load.
- Existing publication/track distinction, queue continuation, feedback origin and named-source behaviour.
- Existing generated slot vocabularies, normalisation guards, SSML escaping and request-type response restrictions.
- The skill, outbound-event and proactive-notification Lambda entrypoints, plus the resolver diagnostic.
- Backend ownership of the catalogue and complete event projections. Do not rebuild those databases in the skill.
- The removal of reminder functionality recorded in the baseline commit. Do not restore reminder classes, tokens, permissions or cancellation code while moving feedback code. [R1]

Do not label a source mechanism as device-tested or production-verified merely because it is present.

## 2. Source-grounded changes to prioritise

| ID | Observed source behaviour | Required change |
|---|---|---|
| A01 | `ApplicationContainer` accepts `**components`, passes `deps=self` to features and uses `inspect.signature` to decide construction. | Replace reflective construction and service-location with explicit, typed factories and constructor dependencies. |
| A02 | Play handlers construct their own feature actions. | Inject actions into controllers; construct them only in the composition root. |
| A03 | Feature models, including search, read Alexa requests and construct Alexa responses. | Move input interpretation and response presentation to the Alexa/controller boundary; use typed commands and outcomes inside models. |
| A04 | `User` and `RequestContext` centralise dictionary access but feature operations still receive `handler_input`. | Evolve those existing gateways so feature classes work without an Alexa SDK object. |
| A05 | `main.py` caches the skill and container. | Keep infrastructure reusable, but never attach a current listener or mutable request state to those cached objects. |
| A06 | `HttpPool` caches by event loop, while callers supply base URL and headers to `get`. | Bind one pool to one upstream configuration, reject mismatched reuse, and keep Hear/Resolver pools separate. |
| A07 | Resolver caching is disabled by `alexa_user_id`, not by `listener_id`; the cache key is utterance/timezone/country. | Disable shared result caching for either form of listener identity; explicitly scope any future personalised cache. |
| A08 | `SavePersistenceInterceptor` catches write errors and the runtime can still return the previously prepared response. | Make essential commits part of action success and return an appropriate failure outcome when they fail. |
| A09 | Explicit `memory` persistence is selected before the production/staging table guard; unknown drivers fall through with a warning. | Reject memory in deployed environments requiring durability and reject unknown driver values. |
| A10 | Outbound consumption skips invalid JSON without adding a batch failure. | Validate every envelope; fail or durably quarantine invalid records rather than silently acknowledging them. |
| A11 | Follow/report event IDs are based on listener/action/subject rather than a distinct operation occurrence. | Verify backend deduplication semantics; make each logical action occurrence unique while keeping retries of that occurrence stable. |
| A12 | DynamoDB scopes are saved through concurrent individual operations. | Keep independent writes where appropriate, but implement an actual transaction for coupled essential changes. A wrapper alone does not create atomicity. |

These observations concern the implementation at the pinned commit. A07 and A11 describe risk conditions, not proof that an observed production incident has already occurred. [R2–R10]

## 3. Architectural ownership and dependency direction

### 3.1 Retain the existing layout

```text
hear-py/
├── main.py
├── config/
├── src/
│   ├── application.py
│   ├── container.py
│   ├── registry.py
│   ├── alexa/
│   ├── controllers/
│   ├── middleware/
│   ├── models/
│   ├── services/
│   ├── clients/
│   ├── database/
│   ├── constants/
│   └── utils/
├── schemas/
├── tests/
├── docs/
├── scripts/
├── .agents/skills/hear-architecture-refactor/
├── .github/workflows/
├── en-GB.json
├── requirements.txt
├── ruff.toml
├── template.yaml
└── samconfig.toml
```

Do not create parallel `actions`, `handlers`, `adapters`, `presenters`, `repositories`, `runtime`, `core` or `common` packages. The existing `alexa/` directory is the presentation and platform-integration boundary. Presentation classes can live there without creating another presentation package.

The repository's class-only convention remains in force under `src`: imports and class definitions at module level, focused enums/constants, static utility methods for pure transformations, and no new code comments. Names, types and tests must explain the implementation. This is a project convention, not a universal requirement for Python. Do not turn every scalar helper into a stateful service merely to increase the class count. [R2]

### 3.2 Responsibilities

| Owner | Responsibility | Must not do |
|---|---|---|
| `main.py` | Lambda event-source boundary and event-loop execution | Feature decisions or a single spoken fallback for every event source |
| `Application` | Validate configuration and assemble runtime infrastructure | Hold the current listener |
| `ApplicationContainer` | Explicitly construct infrastructure and request-specific object graphs | Be resolved from feature code |
| `RouteRegistry` | One authoritative route order and request graph binding | Hide feature business logic in factories |
| `alexa/` | Parse envelopes, adapt commands, format speech/directives and validate responses | Query DynamoDB or decide catalogue policy |
| Controllers | Match a request, call an injected feature action, present its result | Construct dependencies, perform HTTP calls or write state dictionaries |
| Middleware | Deadline, identity, state loading, context validation and lifecycle policies | Become a second search, feedback or playback implementation |
| Models | Typed domain values, feature decisions and state transitions | Import the Alexa SDK, `httpx`, `boto3` or concrete persistence implementations |
| Services | Necessary coordination of external integrations and workers | Duplicate feature rules already owned by a model |
| Clients | External request/response contracts, authentication and transport | Read the current User or decide spoken prompts |
| Database | Storage implementation, conditional writes, transactions and retention | Parse Alexa envelopes or determine feedback policy |
| Utilities | Deterministic reusable transformations | Discover the current listener, perform I/O or mutate shared state |

Define narrow collaborator protocols alongside their owning model where needed. For example, a catalogue search protocol belongs with search's typed inputs/results and is implemented by `HearApiClient`. Avoid a new universal interfaces directory. Infrastructure can import those domain contracts; the domain must not import its concrete HTTP implementation.

## 4. Constructors, factories and lifetimes

### 4.1 Replace the whole-container pattern

Remove from migrated production code:

```text
__init__(..., deps: object | None = None)
self._deps = deps
getattr(deps, "heara", None) or HearApiClient()
ApplicationContainer() inside a controller/model
Container.resolve(...)
inspect.signature(...) for normal component construction
```

Make required dependencies required constructor parameters. A missing dependency should produce an immediate construction error, not a silent fallback to another client.

Proposed constructor contracts:

| Class | Required collaborators |
|---|---|
| `PlayContentHandler` | `PlayContent`, an Alexa presentation collaborator |
| `PlayContent` | Search/catalogue collaborator, playback collaborator, request-owned `User` |
| `Search` | Catalogue protocol, filter/query policy and any explicitly needed feature collaborator |
| `ResolverWorkflowRunner` | Resolver protocol, relevant dialogue/selection policy, request-owned `User` |
| `Playback` | Playback state/queue collaborators and event-staging collaborator |
| `FeedbackService` | Feedback policy, request-owned `User`, event-staging collaborator |
| `HearApiClient` | Validated options, immutable identity, upstream-bound transport/pool |
| `ResolverClient` | Validated options, immutable identity or explicit diagnostic mode, upstream-bound transport/pool |
| `IdentityInterceptor` | Identity resolution service and request-context gateway |
| Persistence interceptors | Persistence coordinator, deadline policy and diagnostics |

Refine the exact argument list from actual method usage. Do not inject an entire RequestComponents object merely to rename `deps`.

Constructors must not call APIs, load storage, resolve identities, enqueue messages or initialise a playback queue. Use explicit asynchronous operations for I/O.

### 4.2 One composition root, two lifetimes

`ApplicationContainer` remains the sole composition root. It can expose explicit methods such as `build_skill_resources`, `build_request_components`, `build_outbound_worker` and `build_notification_worker`. A typed request-components record is a construction result, not a second service container. Only runtime/registry assembly receives it.

Application-lifetime resources: validated settings, upstream-bound pools, database client resources, stateless policies, route declarations, application-level authentication resources and operational instrumentation.

Request-lifetime objects: request metadata, deadline, captured identity, loaded User state, dirty-field tracking, listener-bound clients, commands, outcomes, response builder and any feature/controller instance containing those objects.

Worker-lifetime infrastructure can be shared. Listener-specific data must be created per message, not once per SQS batch. Separate record failures must not leave another record's identity or payload in a worker property.

Do not reset a global `current_user` between requests and call that request scoping. Correctness must come from separate objects. Infrastructure reuse must also respect event-loop lifetime. [E1]

### 4.3 Route registration without shared mutable handlers

Keep route declarations long-lived. Build request-bound controller instances into a local collection for dispatch. Do not clear and repopulate the shared skill's handler list on each invocation.

A staged request graph is acceptable: first build the bootstrap context and identity/persistence interceptors; after identity and User loading, build listener-bound clients and feature controllers. This solves the dependency cycle without a mutable global client identity.

Do not build every feature's I/O resources for an outbound-only worker. Reuse the composition root while keeping each entrypoint's graph minimal.

## 5. Typed requests, state and outcomes

Add cohesive data classes to the existing owning modules rather than separate files for every data class.

| Location | Proposed types or responsibilities |
|---|---|
| `models/listener.py` | Reuse `IdentityContext` and `PrincipalType`; distinguish canonical listener, Alexa user, person, device and skill identities |
| `models/search.py` | `SearchRequest`, `SearchResult`, search gateway protocol and typed discovery context |
| `models/availability_request.py` | Typed availability request instead of a loosely shaped options dictionary |
| `models/resolver.py` | Resolver result/entity/status contracts and typed failures |
| `models/playback_state.py` | Playback instance, queue cursor, prepared successor and progress state |
| `models/dialog.py` | Dialogue type, dialogue ID, expiry, choices and continuation metadata |
| `models/feedback.py` | Rating target and feedback-origin values |
| `models/user.py` | Request-owned state gateway, load status, snapshot/change contracts |
| `alexa/context.py` | Current request metadata and access to parsed inputs/User; no second persistent state copy |

Internal names should be consistent Python names; existing wire/storage names remain boundary mappings. Do not rename API JSON fields simply to match internal naming.

Use explicit result categories such as success, empty, ambiguous, invalid request and dependency unavailable. A failed HTTP call is not an empty successful search. Expected ambiguity is not an unexpected exception.

Avoid mutually contradictory result flags. Make invalid combinations impossible or reject them during validation. Preserve external DTO compatibility at the client boundary while migrating internal results.

Any remaining dictionary must have a documented boundary purpose. Do not replace every `dict` with `dict[str, Any]` and call the model typed.

## 6. Runtime and request lifecycle

Implement the following logical phases in the existing runtime; do not create a competing execution engine:

```text
Validate/classify event and permitted application
→ construct request context, correlation and deadline
→ capture platform identity
→ resolve canonical identity when this operation requires it
→ configure persistence identity
→ load necessary state once
→ build request-bound collaborators
→ validate dialogue and interpret the request where required
→ choose one controller
→ execute a feature action against request-owned state
→ prepare and validate a request-type-compatible response
→ commit essential changes
→ return the validated response
→ finish safe logging and cleanup
```

The preparation phase may assemble an outcome before persistence, but an essential write must succeed before the final response claims the action succeeded. If commit fails, replace the outcome with its failure presentation and validate that response too.

`can_handle` must be deterministic and free of I/O or mutations. It must not call the resolver, advance a queue, consume feedback or construct a response. Matching errors need diagnostic visibility; unexpected match failures must not silently masquerade as a routine fallback.

Keep the existing runtime explicitly asynchronous. Its custom invocation behaviour must be covered by tests rather than assumed to be identical to the standard ASK SDK. [R6]

### 6.1 Interceptor contracts

Choose one signature per interceptor category and migrate every implementation. A recommended contract is a typed context for request interceptors and a typed context plus outcome for commit/response processing. Handle documented short-circuit outcomes explicitly.

Remove runtime introspection used only to accommodate mixed static, bound, synchronous and asynchronous production interceptor styles after all callers migrate. A temporary compatibility bridge belongs only at the migration boundary and must have a removal condition.

Do not persist arbitrary partial changes in `finally`. Cleanup and optional telemetry belong there; an action that failed halfway through must not accidentally save its half-written dialogue or queue.

### 6.2 Request-type-aware error responses

Ordinary launch/intent requests may receive an appropriate spoken recovery response. AudioPlayer callbacks must use the response forms allowed for that specific callback. Session-ended and other no-response events must not receive ordinary speech/cards/reprompts.

For `PlaybackNearlyFinished`, test the permitted AudioPlayer directive-only or empty outcome. Test that both the normal error handler and `main.py`'s last-resort fallback enforce the same restrictions. [E2, E3]

Worker failures must remain worker results or exceptions, not Alexa envelopes. A failing resolver diagnostic must remain a diagnostic result.

### 6.3 Deadlines and cancellation

Use one request budget based on remaining Lambda time and the response deadline, with a reserved finalisation margin. Compute each outbound timeout from remaining time and its configured ceiling.

Essential operations need priority, not unbounded execution. Replace any 'reliable means no timeout' path with an explicitly bounded commit/load policy. Retries, backoff and progressive responses must fit within the same budget.

A cancelled await does not prove that a remote write was undone. Preserve operation IDs and reconcile an uncertain result safely. If synchronous AWS calls are offloaded to a thread, configure their SDK timeouts too: cancelling the await does not stop an already-running SDK call.

Redispatch must be bounded, reuse the same loaded state, and not rerun identity resolution or publish the same action twice.

## 7. Middleware and dialogue routing

Retain `RouteRegistry` as the single source of route/interceptor order. Preserve the meaningful baseline ordering unless a regression test demonstrates a necessary behavioural correction.

| Current file | Migration |
|---|---|
| `middleware/deadline.py` | Capture the budget once; stop spreading deadline extraction through features |
| `middleware/identity.py` | Capture/resolve identity and bind it to context; no current-listener singleton |
| `middleware/persistence.py` | Load once, represent unavailable versus absent, delegate commits and propagate essential failures |
| `middleware/dialog_validation.py` | Validate active dialogue and expiry without doing catalogue work |
| `middleware/resolver.py` | Thin request interpretation entrypoint with an injected runner |
| `middleware/confirmation.py` | Delegate confirmation policy; route its gate role through one registry |
| `middleware/feedback_gate.py` | Consume only relevant active feedback answers; preserve unrelated controls |
| `middleware/onboarding_gate.py` | Gate only the necessary onboarding flow and preserve legitimate system controls |

Do not blindly send every request to the resolver. Keep fast paths for control intents, applicable active-dialogue responses, session events, AudioPlayer callbacks and CanFulfill handling.

Resolve 'yes', 'no', ordinal choices and rating answers in the relevant active dialogue. Do not let a stale availability or onboarding flag capture a new unrelated search. Cancellation and safety-critical playback controls must not be trapped behind an irrelevant question.

Keep the original input, canonical resolution and selected command distinct. Do not destructively rewrite the incoming envelope and lose the evidence needed for debugging. 'Raw utterance' means text actually supplied in the request/slots, not an assumed full transcription field.

## 8. Listener identity and client construction

Capture the available platform principal first. Resolve canonical identity through an explicit bootstrap operation before constructing clients that require a canonical listener.

The bootstrap operation must not require the identity it is trying to discover. Keep a narrow identity-client operation or service for that purpose. Keep anonymous resolver diagnostics separate from listener workflows.

Construct `HearApiClient` and `ResolverClient` with the request's immutable identity. Their operation methods should accept feature arguments, not repeated listener identifiers. The client performs endpoint-specific identity mapping centrally.

Reject conflicting identity supplied through a raw payload; do not let a nested dictionary override the constructor's principal. Do not automatically put all identity fields into all endpoints. Preserve each endpoint's actual field allowlist and support requirements.

Canonical listener IDs, Alexa user IDs, person IDs and device IDs are not interchangeable. Never fabricate a canonical ID or use a device ID as a listener ID. A missing `personId` on a callback must not select a previously recognised person from shared memory. Verify the backend's callback identity mapping before changing per-person ownership.

For an operation whose backend contract permits an Alexa alias fallback, use an explicit fallback mode. For a canonical-only operation, fail/defer that operation when canonical identity is unavailable. Do not universally mandate one fallback rule for every endpoint.

Existing identity/profile caches must be inspected for correct skill, environment and principal scoping. They must never function as an implicit current user. Avoid caching tokens/profile payloads across requests; any retained mapping cache must be bounded, expiring and tested for principal isolation.

## 9. Hear/Resolver clients, filters and transport

### 9.1 One central filter owner

Evolve `SearchFilters` in `src/utils/filters.py`. It is already present; do not add a competing generic filter builder. [R8]

Its responsibilities are pure validation and normalisation of filter values: known keys, supported value types, stable deduplication, dates and explicitly defined source replacement. It must not read User, parse Alexa requests, call a resolver or choose spoken prompts.

Move conversational phrase interpretation out of the filter responsibility into its existing resolver/search-policy owner. Retain useful pure helpers only where they have real callers. Do not change matching thresholds as a side effect of relocation.

The client automatically invokes the common filter policy before serializing a supported request. Callers do not get an undocumented bypass around validation. Endpoint-specific payload mapping remains separate because search and availability do not necessarily accept identical bodies.

### 9.2 Payload ownership

`SearchPayload` becomes a pure boundary mapper: typed query + validated filter + explicit location context + pagination/sort → the documented payload. It must not discover identity or fetch User state.

Keep listener fields out of persisted reusable search plans. Rebind the current verified identity when a plan is replayed. Persist only the query/filter/pagination/discovery information needed to continue the intended queue.

`clients/availability.py` should own availability response mapping, not an independent conflicting source of filter semantics. `utils/listener_payload.py` remains the allowlisted mapper for supported identity/registration payloads.

Required filter behaviour:

| Case | Required result |
|---|---|
| `False` and numeric zero | Preserve when valid; do not discard through truthiness checks |
| Empty string/list | Distinguish absent from intentionally empty according to the contract |
| IDs | Validate supported types; stable deduplicate without reordering meaningful input |
| Caller-owned lists/dictionaries | Do not mutate them or return shared mutable references |
| Category/tag versus entity IDs | Keep distinct; no guessed conversion between display names and IDs |
| Explicit requested city | Takes precedence over a saved locality |
| New city plus old saved coordinates | Do not mix them into one location |
| 'Near me' with no usable locality | Return a location-required outcome rather than inventing a location |
| Date windows | Validate ordering, units and documented endpoint interpretation |
| Source selection | Preserve explicit combination semantics; use source replacement only for an intentional new selection |
| Pagination | Follow the documented index base and stable ordering; do not convert blindly |
| Unsupported filter combination | Fail explicitly or return a typed unsupported result; never silently widen the search |

Date interpretation for the UK skill must use its configured UK timezone/country, not the developer's local timezone. Do not change timestamp units while refactoring.

### 9.3 Resolver result ownership

Use a validated slot/entity resolution when appropriate and retain the existing resolver fallback for unresolved input. Do not treat a raw custom-slot value as proof that an entity ID was successfully resolved.

Preserve canonical entity type, ID, display name, raw phrase and resolution status independently. A downstream string comparison must not discard a verified canonical ID merely because the spoken phrase was an abbreviation.

Represent ambiguity explicitly, persist the intended choices with their dialogue ID, and resolve a selection against those choices before starting another unrelated interpretation flow.

Keep search interpretation separate from search execution. The resolver should not become the skill's catalogue database, and the catalogue client should not become a second resolver.

### 9.4 Cache correctness

Immediately change shared resolver-cache eligibility from 'no Alexa user ID' to 'no listener identity of either supported kind and no other contextual/personal input'. This is a conservative default for the current cache shape. [R7]

If personalised caching is subsequently required, design and test a full context key: canonical principal, skill/environment, locale/country/timezone, relevant dialogue/location context and contract/model version. Do not add personal caching merely as part of this refactor.

Do not return a mutable cached result that a caller can modify for another request. Preserve immutable values or return a safe copy. Error and ambiguous-result caching require an explicit policy, not accidental reuse.

### 9.5 Transport rules

Prefer one configured pool per upstream. Bind base URL, application authentication configuration, connection limits and circuit state when constructing that pool. Simplify `get` so it cannot silently change upstream configuration after first use. Keep identity per request, not in shared mutable headers. [R9]

Centralise transport mechanics once: request timing, bounded retries, status classification, safe logging and JSON decoding. Do not move endpoint-specific validation into a universal transport class.

Retry only operations that are safe to repeat. Read-like POST searches/resolution may be retryable; writes need a supported idempotency contract. Handle 429/Retry-After and transient 5xx within the remaining deadline. Do not retry ordinary validation/authentication failures as if they were transient search misses.

Separate permanent dependency errors, transient failures, invalid response schemas and empty results. A 2xx response with an invalid body is a contract failure, not a successful empty result.

Close resources on explicit test/application shutdown and before discarding a managed loop where feasible. Do not close the shared pool after every request. Never reuse a closed loop's client in a new loop.

## 10. User state and storage implementation

### 10.1 Keep User as the only feature-facing persistent state gateway

Make `User` a request-owned object with semantic operations and typed views. Feature code should express `begin_confirmation`, `record_feedback`, `start_playback`, `prepare_successor`, `clear_dialog` or equivalent cohesive methods, not arbitrary string-key updates.

Do not introduce another ListenerStore or PlaybackRepository that writes the same state independently. `Listener` should continue to derive listener-facing state through User and its supplied identity.

The existing RequestContext is the sole transient request gateway. It can expose the request's User, but must not maintain a competing mutable copy of the same persistent state.

### 10.2 One schema, fresh defaults, explicit serialization

Keep `StateSchema` as the persistence field/scope registry. Preserve its current field classifications during the first migration phase. In particular, `listenerId`, names, email and address fields currently marked non-persisted must not become persistent merely because they appear in a new data class. [R5]

Change mutable default handling to use fresh values. Hydrating two new users must create independent lists/dictionaries, including nested collections. A snapshot must not expose nested mutable state that bypasses dirty tracking.

Use explicit serializers/normalisers tied to the existing registry; never serialize an entire service/context object using a generic dump. Storage schema/version, default construction and persisted-field selection must agree through tests, not separately maintained hand-written lists.

Keep legacy migration and normalization in cohesive collaborators owned by the User state contract. Database code performs storage mechanics against a resolved key and serialized document; it must not inspect an Alexa envelope. Avoid a circular import by making the key/serialization contract framework-independent.

### 10.3 Load states and failures

Represent `loaded`, `new`, `unavailable` and `unsupported_or_corrupt` distinctly. 'No item exists' is different from 'the read failed'. Do not catch every read failure and turn it into a new user.

When load is unavailable, preserve the current no-save guard. Do not reset onboarding, clear a queue, or overwrite an existing dialogue with defaults. Commands requiring durable state should return an appropriate unavailable outcome; safe stateless operations can proceed without pretending state was saved.

Initially keep the existing required-scope loading behaviour. Introduce selective scope reads only after measuring need and defining all required scopes for each request. A failed required-scope read must not be hidden by successful optional cache reads.

### 10.4 Commit contract

The persistence coordinator should return a typed result identifying success, no change, unavailable load, conflict exhaustion, deadline exceeded, invalid state or an uncertain remote outcome.

On confirmed success, update the request's saved versions and baseline and clear only successfully committed dirty fields. Never mark a failed write clean. Never allow a second response interceptor to repeat the same commit automatically.

A failed action should discard its uncommitted action changes. Preserve separately defined valid observations only when their independent commit policy permits it. Do not use an all-purpose finalizer that persists every mutation regardless of outcome.

Classify essential versus optional state by operation. Playback successor reservations, feedback answers and pending confirmations are not equivalent to a best-effort diagnostic counter.

### 10.5 Concurrency and atomicity

Retain optimistic concurrency per scope. Use meaningful operations when reconciling conflicts; do not blindly merge entire old dictionaries over fresh state.

Use atomic transactions when essential invariants span scopes—for example, recording a feedback completion and its continuation state, or consuming a dialogue and establishing the intended playback transition. Include version conditions on the update actions themselves.

Do not assume concurrent consistent reads produce a single multi-item snapshot. Use a transactional read when an invariant actually needs an atomic multi-scope view; otherwise document the independent-read semantics. DynamoDB's transaction operations provide the all-or-nothing mechanism, not `asyncio.gather`. [E4]

Do not reuse an identical DynamoDB client request token for a changed transaction body after conflict re-evaluation. Keep logical action idempotency distinct from individual transaction-attempt idempotency.

### 10.6 TTL, item size and storage migrations

Check expiry in application/read logic. DynamoDB TTL deletion is asynchronous, so an expired document may still be returned. An expired dialogue must not be accepted because its physical row still exists. [E5]

Bound queue/history/cache collections without dropping the active item or corrupting its cursor. When a bounded window is persisted, preserve enough continuation state to retrieve the next page. Keep AWS numeric serialization constraints and reject invalid numeric values before storage.

Preserve the current physical key format and four scopes in the initial architecture release. A pure class refactor does not require renaming the table or bumping the stored schema.

If a physical shape changes, add explicit versioned read migration and tested compatibility with the previous deployed reader. Unknown newer versions must not be silently reset and overwritten. Make migrations deterministic, repeatable and safe on partially migrated records.

Alias-to-canonical migration must not overwrite newer canonical data. Test existing/absent/partial canonical records and conflicts before changing migration semantics. Never delete the old representation until the deployed-reader compatibility requirement has actually ended.

## 11. Playback, queues, feedback and recovery

### 11.1 Playback instance identity

Keep content identity separate from playback-instance identity. Replaying the same recording, restarting at a different speed and moving to another queue are not necessarily the same playback occurrence.

Associate accepted events with the intended queue, playback instance and generation. Retain/request a stable event identifier for duplicate detection. Do not use lexicographic ordering of Alexa request IDs as a time sequence.

A robust token design must distinguish relevant playback generations without exposing raw listener identifiers. Any token-format change needs a versioned decoder and a compatibility path for audio already playing with old tokens. Do not suddenly reject all current devices' callbacks after deployment.

### 11.2 Queue rules

There must be one owner for queue movement. Search, feedback, the next control, and AudioPlayer callbacks must call it rather than maintain separate queue-index logic.

`PlaybackNearlyFinished` may prepare/reserve and enqueue a successor, but must not pretend the successor is already playing. Confirm active-item movement against the appropriate started event and queue identity. Preserve the exact predecessor token in an enqueue directive.

Duplicate preparation or callback handling must not enqueue the same successor twice. A late event from an old playback instance must not modify a newer queue. Seeking or speed changes must not look like completion or double-count listening time.

Persist the active cursor, normalized source/query, next-page information and required prepared successor. Keep lazy pagination: fetch the next page when needed, not every page during the initial request. Empty pages, missing items, failed fetches and end-of-queue require distinct outcomes.

Queue state must recover on a new invocation without session attributes. AudioPlayer requests do not provide a skill session in the same way as ordinary conversational requests. [E2, E3]

### 11.3 Feedback target and origin

Capture the rating target before collecting an answer: subject type/ID, applicable track/publication identity, playback instance, queue ID/index, canonical spoken subject, feedback operation ID and origin.

Do not select the target later from whichever item happens to be first in history or whichever search most recently ran.

Keep mid-playback rating separate from a return-launch feedback question. The mid-playback path must preserve the intended next-track/continuation behaviour without repeating advancement. The return-launch path must ask whether to continue the exact named source where required by the product flow.

After a saved/accepted answer, clear the completed rating question atomically with its applicable continuation state. An 'enjoyed' answer must not be consumed again by an unrelated yes/no gate.

Retain existing enjoyed/not-enjoyed/somewhat synonyms and recognition work. Do not reimplement vocabulary already fixed. Add a regression only for a demonstrable missing mapping or routing defect.

### 11.4 Lost or expired dialogue recovery

Dialogue state must carry a dialogue ID, kind, creation/expiry time and only the context needed to answer it. Ensure legacy `awaiting...` flags are derived/updated through one owner rather than independently mutated by unrelated features.

When a dialogue expires, clear its conversational state without destroying the playback queue. A stale confirmation must not play a newly searched item. An unrelated new command should replace or dismiss the old conversational context through an explicit rule.

Do not rely on an in-process task or a surviving microphone session for recovery. Persist the state needed for a later legitimate invocation; stop where identity or state cannot be safely recovered.

## 12. Events, workers and durable acknowledgements

### 12.1 Operation identity

Create a logical operation ID when an action starts, and keep it stable through retries and pending confirmation. Different legitimate occurrences must have different IDs.

Test a full follow → unfollow → follow sequence. The second follow must not be suppressed by deduplication intended for retries. Likewise, a retry of the same report should reuse its ID, while a genuinely new report must not be permanently suppressed by the old subject-only ID. Verify the backend contract before changing its accepted envelope. [R10]

Freeze the event envelope for an operation: schema version, event ID, timestamp, type and body. Do not regenerate timestamps/IDs on every transport retry. Preserve supported signing and payload contracts.

### 12.2 Resolve the state/event dual-write boundary

The existing SQS publication and DynamoDB update paths must not be described as one atomic operation. Simply awaiting both does not close the failure window between them.

For feature actions requiring both durable local state and durable event acceptance, implement a transactional outbox as a separate, explicitly deployed reliability stage. The chosen target is:

```text
Feature stages state change + stable event
→ DynamoDB transaction commits both
→ outbox relay sends the committed event to the existing outbound SQS queue
→ existing outbound consumer forwards it to the backend
→ backend deduplicates by the stable event ID
```

Use the existing table only if an additive item type is compatible with its access patterns and deployment. Preserve `CORE`, `PLAYBACK`, `DIALOG` and `CACHE` as the only listener-state scopes; an outbox record is an operational item, not a fifth state aggregate.

A proposed outbox sort key is `OUTBOX#<eventId>`, under the existing resolved persistence key. Keep an explicit record type, immutable event envelope, creation time, delivery state, attempt/lease information where needed and terminal retention metadata. The regular User loader must request its four known scopes, not hydrate outbox records as listener fields.

The relay can use DynamoDB Streams, but pending records need a durable replay/reconciliation route too. Use a bounded pending-work access pattern, not a full table scan on each invocation. Enable the relay, its failure handling, recovery path and alarms before enabling outbox-producing feature code.

Do not expire undelivered work merely to control table size. Apply cleanup after successful queue acceptance or deliberate durable dead-letter/quarantine handling.

A crash after queue acceptance but before marking the outbox record delivered may cause a duplicate send. That is why the stable event ID and idempotent consumer remain required. Do not promise exactly-once delivery. [E6]

This is an explicit reliability extension, not a prerequisite for renaming classes. The foundation migration may land first, but the combined durable state/event guarantee must remain OPEN until the complete path is deployed and tested.

If the deployed backend instead provides a documented atomic, idempotent operation that can safely own the action, record that contract and replace the outbox requirement only through an explicit architecture decision. Do not invent such an endpoint.

### 12.3 Worker error handling

Validate JSON and the event schema for every record. Invalid JSON, missing required fields and unsupported event versions must not be silently skipped. Use SQS redrive/partial failures or an explicit durable quarantine; acknowledge only after the selected handling succeeds.

Return the failed record identifiers correctly. For a missing identifier or an unrecoverable batch-level failure, use the documented batch failure behaviour rather than accidentally treating the batch as successful. Preserve already-delivered messages through idempotency on retries. [E7]

Keep bounded processing time per batch and record. Do not throw away the Lambda context/deadline for workers that perform network calls. Retryable failures and permanent rejection must be distinguishable in metrics and logs.

Retain the configured queue type. Do not introduce FIFO as an unrelated architectural change. If FIFO is actually used, implement its partial-batch ordering rules correctly.

### 12.4 Proactive notifications

Keep the spoken inbox and proactive delivery as separate entrypoint workflows sharing one documented backend notification contract. Keep notification storage backend-owned.

Create listener-bound request data per notification record. Reuse only application-level transport/authentication resources. Do not pass one listener's delivery target into another record.

Treat a permanent not-enabled/invalid-target response differently from a retryable network failure. Record actual delivery outcomes; don't mark a timeout as definitely delivered. Retry and deduplication policy must account for an unknown remote outcome.

Do not claim exactly-once proactive delivery when the external service does not supply such a guarantee. Keep application credentials, transient delivery targets and canonical notification IDs distinct. Preserve the existing canonical-only notification lookup rules unless the backend contract explicitly changes.

## 13. Feature-by-feature model migration

For each group below, keep the current public behaviour and move only the responsibilities that violate the boundaries. Return typed outcomes and remove `handler_input`, raw request/session dictionaries and `deps` from the migrated feature layer.

| Existing model file(s) | Required owner and changes |
|---|---|
| `models/play.py` | Keep `PlayContent` and organisation playback orchestration. Inject search/availability/playback/User. Return a play, choice, empty or unavailable outcome; do not format Alexa responses. |
| `models/search.py` | Own the search workflow and typed results. Move slot parsing and response construction out. Centralise search execution, canonical subject context and lazy-page metadata. |
| `models/resolver.py` | Keep validated resolver contracts and interpretation policies. Separate external payload mapping from feature decisions where currently mixed. |
| `models/resolver_runner.py`, `models/resolver_workflow.py` | Make the runner's dependencies explicit. Split request extraction from pure interpretation and dialogue decisions. Keep one resolver call owner and one canonical result; no runner/service/wrapper chain that repeats the same operation. |
| `models/availability.py`, `models/availability_data.py`, `models/availability_request.py`, `models/availability_dialog.py` | Separate typed availability input/result, catalogue calls, format-choice policy and dialogue transitions. Reuse the shared filter owner. Preserve selected source and pagination through the choice. |
| `models/browse.py` | Own browsing/selection and cursor policy. Reuse catalogue/search and queue services rather than reconstructing their payloads and playback rules. |
| `models/playback.py`, `models/playback_state.py` | One playback state machine and queue mutation path. Remove raw Alexa response building; produce a typed playback instruction for the platform boundary. |
| `models/playback_controls.py` | Delegate pause/resume/next/previous/repeat/seek/speed changes to the same playback owner; no independent state-copy logic. |
| `models/playback_events.py` | Apply validated event observations idempotently to the matching playback instance. No conversational response construction. |
| `models/playback_history.py` | Keep bounded continuity information and required state transitions; full history remains backend-owned. |
| `models/feedback.py`, `models/feedback_response.py` | Own eligibility, rating target, origin, answer and continuation policy. Stage reliable events and state changes; no duplicate feedback store or prompt system. |
| `models/dialog.py`, `models/confirmation.py`, `models/affirmative.py`, `models/decline.py` | One active-dialogue interpretation path. Refactor yes/no handling into cohesive collaborators by dialogue kind; avoid giant unrelated branching models. Keep one active state owner. |
| `models/intent_dispatch.py` | Choose a typed feature command from validated interpretation. Alexa handler registration remains in the registry; no recursive routing maze. |
| `models/launch_workflow.py` | Decide returning-user/onboarding/resume/feedback outcomes from identity and loaded state. No hidden profile API construction or blanket reset on a load failure. |
| `models/onboarding.py`, `models/onboarding_state.py`, `models/permission.py` | Own onboarding/permission decisions and progression; move SDK requests/cards to the boundary and external profile calls to injected integrations. |
| `models/listener.py`, `models/user.py` | Reuse identity and sole state gateway. Remove raw HandlerInput access from their feature-facing operations; do not introduce a parallel listener store. |
| `models/notifications.py` | Own spoken notification selection/playback outcomes while querying an injected backend client. Do not persist a second notification inbox. |
| `models/social.py` | Follow/unfollow/creator workflows use canonical targets and occurrence-specific operation IDs. Preserve organisation versus creator semantics. |
| `models/report.py` | Capture/report the intended subject, stage the event and return a typed acknowledgement/continuation. Do not make a new search overwrite the report target. |
| `models/suggestion.py` | Own suggestion progression/exclusions with bounded state and explicit expiry; reuse catalogue and dialogue policies. |

The model filenames above were enumerated from the pinned repository tree. The matrix is an implementation ownership map, not a claim that every listed module needs a wholesale rewrite. [R11]

### 13.1 Product flow invariants

An organisation or creator request must retain the selected canonical entity, obtain publication/track availability and offer the intended format choice. Offer only available formats; when both exist, preserve the publication-first presentation and explicit counts.

A location discovery should list the relevant organisations and creators, then run the same selected-source availability flow. Do not bypass that flow with a different location-specific playback implementation.

A publication selection must preserve its ordered tracks. Do not apply 'unheard publication first' ordering inside the publication's track list. Previously listened-to publication ordering must use the established product policy and available history, not an invented local full-history store.

Use canonical organisation, creator or publication names in their playback/continuation speech. General topic/category/tag searches may use a topic label. Do not insert `short_description` before source/publication playback while restructuring the presentation layer.

Playback speed changes must use the implemented supported mechanism and preserve queue identity/offset semantics. Do not invent an unsupported AudioPlayer directive field for speed. Retain behaviour tests for available speed variants and unsupported requests.

## 14. File-by-file change map outside the models

### 14.1 Entry, configuration and composition

| File | Work |
|---|---|
| `main.py` | Preserve existing handlers/diagnostic. Keep shared infrastructure only. Pass worker deadlines onward. Make the outer error fallback event-source/request-type aware. Add an outbox entrypoint only in the separately deployed reliability stage. |
| `config/__init__.py` | Keep central settings ownership. Validate persistence driver/environment, required URLs/secrets and timeout/limit ranges at startup. Inject validated options; do not spread settings reads through models. |
| `config/permission_scopes.py` | Keep only scopes genuinely required by supported features; do not restore removed reminder permissions. |
| `.env.example` | Document every supported non-secret configuration option; remove obsolete options after all consumers migrate. |
| `src/application.py` | Build runtime and persistence explicitly; fail fast on invalid durable-storage configuration. No hidden creation of listener state. |
| `src/container.py` | Replace reflective/`**components` construction with typed factories and exact injection. Add request/worker graph builders; make every replaceable component actually injectable, including search. |
| `src/registry.py` | Keep one ordered route catalogue; bind request-specific handler instances locally, not into shared mutable arrays. Test precedence and coverage. |

### 14.2 Alexa integration and presentation

| File/group | Work |
|---|---|
| `src/alexa/runtime.py` | Implement staged request graph, consistent interceptor signatures, typed action results, explicit commit outcome handling, bounded redispatch and event-aware final envelope validation. |
| `src/alexa/context.py` | Evolve the existing RequestContext into the transient boundary; create it once; no duplicate persistent User dictionary. |
| `src/alexa/request.py` | Centralise envelope/slot extraction, request classification and validated platform identity input. No feature-level catalogue policy. |
| `src/alexa/response.py` | Own final response adaptation/validation, including last-resort response policy for each request type. |
| `src/alexa/entities.py` | Keep dynamic-entity/directive adaptation in the platform layer; consume validated choice models. |
| `src/alexa/speech.py`, `src/alexa/search_speech.py`, other existing speech modules | One owner per prompt/formatting rule; consume typed outcomes and canonical subject labels. Preserve British English and established wording. |
| `src/alexa/ssml.py` | Retain escaping/formatting tests; untrusted text must not become arbitrary SSML markup. |
| Other existing `src/alexa/*.py` | Classify through the same boundary. Preserve coherent platform utilities; remove only demonstrated duplicate wrappers after caller migration. |

### 14.3 Controllers

Apply thin constructor injection and typed input/output adaptation to every registered controller, including these current groups:

| Files under `src/controllers/` | Work |
|---|---|
| `play.py`, `browse.py`, `availability.py` | Inject the relevant model and presentation collaborator; remove dependency construction and payload/state logic. |
| `launch.py`, `permission.py` | Map launch/town/permission inputs to model commands; adapt cards and conversational outcomes at the boundary. |
| `feedback.py`, `confirmation.py` | Map answers to the correct typed dialogue/feedback command; do not duplicate target/origin policy. |
| `playback_controls.py`, `playback_events.py` | Parse controls/events and delegate to shared playback owners; enforce callback response policy. |
| `notifications.py`, `social.py`, `report.py` | Resolve input contracts and invoke one injected feature workflow; no hidden API clients. |
| `intent_dispatch.py`, `fallback.py` | Use explicit validated routing outcomes and bounded re-dispatch; do not mutate/replay the entire request lifecycle. |
| `can_fulfill.py`, `system.py`, `error.py` | Preserve matching precedence and request-type constraints. Keep help, cancellation, session-ended and error responses out of business models. |

For any additional controller found in the live checkout, apply the same rules and record its route/test. Do not delete dynamically registered handlers because static imports appear absent.

### 14.4 All current client modules

| File under `src/clients/` | Work |
|---|---|
| `hear.py` | Listener-bound identity, typed search/availability/listener contracts, shared filter mapping and explicit error results. Keep bootstrap identity operations separate from canonical-only calls. |
| `resolver.py` | Listener-bound invocation, anonymous diagnostic mode, safe cache eligibility, validated results and redacted diagnostics. |
| `availability.py` | Availability response/payload translation only; no independent conflicting filter policy. |
| `pool.py` | Upstream-bound loop-safe pooling, correctly scoped circuit state, explicit lifecycle and no shared mutable listener headers. |
| `events.py` | Stable envelope transmission, bounded AWS/HTTP operations, real failure propagation and supported signing/idempotency. |
| `notifications.py` | Canonical notification contract, per-request/per-record identity binding and explicit delivery/read/update outcomes. |
| `proactive.py` | Application authentication and Alexa delivery transport; distinguish permanent target errors, retryable errors and unknown outcomes. |
| `progressive.py` | Best-effort progressive responses within the shared request budget; never block an essential action or send for unsupported event types. |
| `alexa_settings.py` | Platform profile/locality transport with explicit permission failures, endpoint validation and per-request tokens. |
| `alexa.py` | Retain only a cohesive integration responsibility with real callers; collapse a pass-through wrapper only after call graph and contract tests prove it redundant. |

### 14.5 All current service modules

| File under `src/services/` | Work |
|---|---|
| `listener_identity.py` | Explicit bootstrap/resolve workflow, correct principal mapping and safe cache policy; no raw state mutation outside User. |
| `listener_sync.py` | Use the supported listener payload contract and injected bootstrap/bound client as appropriate. No duplicate registration/sync policy. |
| `alexa_locality.py` | External locality coordination with explicit permissions and authoritative requested-versus-saved location semantics. |
| `alexa_profile.py` | Fetch/map permitted profile information; keep sensitive fields transient unless already expressly persisted. |
| `events.py` | Stage/publish stable operations, correct follow/report occurrence IDs, validate worker input and return proper failures. Split transport and feature policy without another duplicate event pipeline. |
| `notification_delivery.py` | Per-record canonical identity and deadlines, idempotent/reconcilable delivery workflow and actual outcome reporting. |
| `observability.py` | Structured redacted errors, correlation, dependency timings and commit outcomes. No raw request/body dump as default logging. |
| `logging_control.py` | Central configuration only; avoid competing root-log-level overrides during request handling. |

### 14.6 Database and utilities

| File/group | Work |
|---|---|
| `src/database/persistence.py` | Typed persistence interface/coordinator and parity-tested in-memory implementation. Keep one commit path. |
| `src/database/dynamo_user.py` | Framework-independent resolved key, explicit load/commit outcomes, preserved conditional writes, expiry handling and transaction integration. |
| `src/database/dynamo_merge.py` | Domain-aware conflict reconciliation with stale-event protection and versioned tests. No unconditional last-writer-wins over whole state. |
| `src/database/dynamodb.py` | Low-level DynamoDB operations, encoding and actual transactional primitives; bounded SDK operations and relevant error classification. |
| `src/constants/state.py` | Single registry, fresh defaults, explicit scope/version/retention policy and no accidental persistence expansion. |
| Other `src/constants/*.py` | One authoritative field/intent/enum definition; no hidden executable workflow or duplicate constants facade. |
| `src/utils/filters.py` | Single pure filter owner; separate conversational/source interpretation responsibility. |
| `src/utils/search_payload.py` | Pure query/pagination/endpoint mapping; no identity discovery or User access. |
| `src/utils/listener_payload.py` | Preserve strict endpoint field allowlists and identity/registration distinctions. |
| `src/utils/content.py`, `src/utils/content_normalizer.py` | Canonical content/subject normalization once; keep raw API adaptation separate from presentation. |
| `src/utils/playback.py`, `src/utils/playback_history.py` | Pure time/identity/history transformations only; queue mutations remain model-owned. |
| `src/utils/browse.py` | Pure pagination/choice transformations; no hidden state or catalogue calls. |
| `src/utils/user_state.py` | Pure bounded collection/serialization support controlled by the User schema. |
| `src/utils/deadline.py` | Budget calculation using supplied context/clock; no repeated raw envelope access. |
| `src/utils/events.py` | Stable allowlisted event construction and occurrence-aware IDs; no external delivery. |
| `src/utils/notifications.py` | Pure notification transformation, no second inbox or delivery workflow. |
| `src/utils/alexa_date.py` | Preserve timezone-aware supported date parsing and boundaries; add UK daylight-saving regression coverage where relevant. |
| Package `__init__.py` files | Keep minimal; no concealed object construction or compatibility re-exports after migration. |

### 14.7 Explicitly new files, only where justified

Most new classes belong in existing modules. The following new paths are justified by independent responsibilities, not required merely to make the tree larger:

| Proposed path | Purpose and gate |
|---|---|
| `src/database/outbox.py` | Operational outbox persistence, added only with the separately deployed reliable state/event stage |
| `src/services/outbox.py` | Relay/recovery workflow with its own worker lifecycle, added with the same stage |
| `tests/test_*.py` files named in section 17 | New regression coverage; extend an equivalent existing test instead of duplicating it |
| `docs/architecture/IMPLEMENTATION_STATUS.md` | Evidence-backed migration ledger |
| `docs/architecture/API_CONSUMER_MAP.md` | Actual call-site/endpoint/contract/deletion map |
| `docs/architecture/STATE_MIGRATION.md` | Only when physical state/token representation changes; version compatibility and rollback plan |

A protocol/data class or a five-line mapper does not automatically require a new module. Any further new production file must have an independent responsibility and production caller recorded in the change report.

## 15. API cleanup and dead-code removal

Do not assume `listeners/register` and `listeners/sync` are duplicates merely because their payloads look similar. Establish the deployed backend's contracts and all consumers first. Do not remove an API on a separate service just because this repository no longer calls it.

Create a consumer map containing: feature or worker entrypoint, controller/model/service, client operation, HTTP method/path, request/response schema, authentication/identity requirement, timeout/retry/idempotency policy, test and migration status.

Treat locally checked-in schemas and current provider OpenAPI as evidence to reconcile, not permission to guess unsupported fields. Pin sanitized contract fixtures used by tests. A server-side builder with a similar name is not automatically code that should be copied into `hear-py`.

Trace each candidate for deletion through imports, registry/factory bindings, tests, worker entrypoints, diagnostics, scripts, interaction-model intents, Docker/Lambda handler settings and deployment workflows.

Do not count 'only used in a test' as an automatic reason to retain dead production code. Instead, determine whether the test is proving a genuine supported contract or merely keeping an obsolete wrapper alive.

Delete obsolete code only after migrated callers and regression tests succeed. Remove unused imports, settings, requirements, schema references and documentation in the same work package. Do not leave deprecated duplicates behind without a concrete mixed-version compatibility requirement and removal condition.

Never run an old bulk migration script blindly over current source. Audit its assumptions and use targeted changes. A previous document's 'zero violations' statement is not evidence that today's modified code passes.

## 16. Security, logging and deployment configuration

Validate the expected skill/application and event source at the appropriate boundary. Preserve the configured Lambda invocation restrictions. A structural event-shape check is not a substitute for the actual trust boundary.

Validate external URLs and application options centrally. Do not accept an arbitrary caller-supplied URL that turns a client into an unrestricted proxy. Preserve certificate validation and supported Amazon API endpoint handling.

Do not log API keys, bearer tokens, complete request envelopes, full profiles, signed audio URLs or unrestricted user utterances. Log allowlisted structure, dependency/result categories, request correlation and a safe principal reference. A short unkeyed text hash is not guaranteed anonymisation for guessable content.

Scope HTTP circuit failures to the upstream. A single user's permission denial must not open an application-wide service outage circuit.

Review `template.yaml`, `.github/workflows/deploy-develop.yml`, `.github/workflows/deploy-main.yml`, `samconfig.toml`, `Dockerfile`, `requirements.txt`, `ruff.toml`, `deploy/*` and `scripts/*` for actual import/entrypoint/config changes. Do not remove a worker, widen IAM permissions or replace a table as a side effect of moving code.

Preserve separate development and production deployment paths. Inspect a change set before any storage/stream/index/worker change. New outbox resources require narrowly scoped IAM, failure routing, retention, recovery and alarms; no deployment is implied merely by this specification.

## 17. Test plan and completion evidence

Add focused tests before changing each behaviour. Use deterministic clocks, fake deadlines and fake clients instead of sleeps/network calls in unit tests. Keep existing end-to-end fixtures and golden responses where they represent correct product behaviour.

The filenames below are proposed targets, not claims that those files already exist. Extend equivalent current tests where practical.

| Proposed test module | Minimum cases |
|---|---|
| `test_request_scope.py` | Two listeners sequentially on one warm application; interleaved request contexts; no identity/state/header crossover; new response builder per request; each SQS record isolated |
| `test_constructor_wiring.py` | Required dependencies fail fast; every route constructs; search replaceable by a fake; no controller constructs a client; no model resolves a container |
| `test_identity_binding.py` | Canonical, supported alias fallback, missing identity, conflicting payload ID, person/skill principal distinction, callback without personId and anonymous diagnostic |
| `test_http_pool_isolation.py` | Hear and Resolver on same event loop; different URLs/authentication never reuse wrong configuration; closed-loop handling; breaker scope; cleanup |
| `test_resolver_cache_isolation.py` | Listener-ID-only requests bypass shared cache; Alexa-ID-only and both-ID requests likewise; anonymous cache hit/expiry; no mutable result contamination |
| `test_search_filters.py` | False/zero, empty/missing, stable dedupe, caller immutability, invalid IDs/types, explicit city over saved locality, stale coordinates excluded, source replacement, date units/ranges, unsupported combinations |
| `test_api_contracts.py` | Exact search/availability/resolver/listener/notification bodies; identity allowlists; no prefix duplication; 2xx malformed JSON/schema; empty versus unavailable; supported retry policy |
| `test_runtime_pipeline.py` | Actual interceptor order; pure matching; short circuit; exception during each phase; essential commit failure changes outcome; bounded redispatch; no duplicate side effects |
| `test_alexa_response_contracts.py` | Launch/intent speech; each supported AudioPlayer callback; no forbidden speech/card/reprompt; SessionEnded; outer last-resort failure; diagnostic and worker outputs remain separate |
| `test_user_state.py` | Fresh defaults including nested values; typed round trip; dirty tracking; no leaked mutable snapshots; no state/service/context serialization; field/scope registry consistency |
| `test_persistence_failure_safety.py` | Absent versus failed load; unavailable load never saved; corrupt/unknown schema never overwritten; essential save timeout; optional save failure; versions/baseline update only after success |
| `test_persistence_concurrency.py` | Concurrent playback and feedback changes; conflict retry cap; stale event rejection; coupled transaction all-or-nothing; independent scopes remain independent; uncertain commit reconciliation |
| `test_state_expiry_migration.py` | Expired-but-still-present item; expired dialogue retains playback; legacy v2 round trip; repeatable migration; canonical versus alias conflicts; mixed reader compatibility |
| `test_playback_queue.py` | First/next/previous/repeat; nearly-finished reservation; duplicate started/finished events; late old-queue callback; same content played again; page boundaries; empty page; API failure; exhausted queue; cold recovery |
| `test_playback_speed_seek.py` | Supported speed variants; seek offset conversion; no duplicate advancement/listening count; queue preserved; old token compatibility |
| `test_feedback_flows.py` | Mid-playback rating; return-launch feedback; latest intended subject; publication/track distinction; known synonyms; unrelated intent not consumed; one durable answer; correct named continuation |
| `test_dialogue_routing.py` | Yes/no and ordinals scoped to active dialogue; cancel/control bypass irrelevant prompts; expiry; new search replaces old context intentionally; selected canonical ID survives |
| `test_availability_browse.py` | Creator/organisation counts; publication-first choice; only available formats; publication track order; location returns relevant source types; named source preserved through pagination |
| `test_event_idempotency.py` | Retry preserves envelope/ID; follow→unfollow→follow produces legitimate distinct operations; report retries versus new reports; playback events deduplicated against intended occurrence |
| `test_worker_failures.py` | Invalid JSON/schema not silently acknowledged; failed item IDs; permanent quarantine failure; partial success; duplicate delivery; deadline; missing identifier handling |
| `test_notification_delivery.py` | Two records for different listeners; permanent not-enabled versus transient failure; timeout/unknown outcome; correct backend outcome; notification state not duplicated locally |
| `test_outbox_delivery.py` | State/event transaction atomicity; crash before/after queue acceptance; replay with stable ID; relay/recovery failure; pending work not expired; backend dedupe; feature remains gated until relay ready |
| `test_configuration.py` | Production/staging memory driver rejected; unknown driver rejected; missing table/secret/URL fails appropriately; local memory remains usable; timeout/limit validation |
| `test_architecture_boundaries.py` | Prohibited imports/access/construction, cycles, dependency locator patterns, duplicate state/filter owners, class-only convention and all registered entrypoints covered |

Architecture tests should inspect real imports, constructor usage and attribute access through AST or equivalent reliable checks. Do not rely only on text grep, line count or 'every file has a class'. Do not weaken assertions or add blanket ignores to make the refactor appear complete.

Run the repository's existing checks from the actual checkout:

```sh
git status --short
git rev-parse HEAD
python .agents/skills/hear-architecture-refactor/scripts/audit_architecture.py . --strict
python -m ruff check src tests
python -m compileall -q main.py src config
python -m pytest -q
```

Also run configuration/entrypoint/schema validation and the project's applicable deployment-template checks. Introduce one type-checking tool only through an explicit development-dependency/CI change; run it on migrated modules and expand coverage rather than adding a tool nobody executes.

Record the exact command, revision, result and failure details. Distinguish unit, contract, integration, deployment and device tests. No test or deployment was executed as part of preparing this document.

## 18. Migration order, rollout and acceptance

### 18.1 Ordered work packages

| Package | Scope | Exit gate |
|---|---|---|
| W00 | Pin checkout; reconcile existing fixes; inventory files/routes/endpoints; baseline tests | Evidence ledger and regression fixtures exist |
| W01 | Validate config; map application/worker infrastructure lifetimes | No hidden listener state in application resources; durable driver validation tested |
| W02 | Explicit constructors and request/record graph factories | No `deps` service-location in migrated paths; all routes construct; isolation tests pass |
| W03 | Evolve RequestContext/User and typed feature commands/results | No feature-layer HandlerInput dependence in the first complete vertical slice |
| W04 | Implement request-type-aware lifecycle, errors and commit outcomes | One successful and one failed request of each relevant type traverse the real runtime correctly |
| W05 | Listener-bound clients, pool isolation, common filters and resolver cache fix | Exact payload/isolation/failure tests pass |
| W06 | Migrate search→availability→play end to end | Canonical source, counts/choices, speech, queue and persistence work through the new boundaries |
| W07 | Migrate playback controls/events/feedback/dialogues | Recovery, duplicate/stale events, rating origin and continuation tests pass |
| W08 | Migrate onboarding, permissions, social, reports, notifications and workers | Every supported feature/entrypoint uses the intended boundaries |
| W09 | Storage hardening, actual coupled transactions and versioned migrations where needed | Concurrency, expiry, rollback/mixed-version tests pass; no table recreation |
| W10 | Add/deploy outbox reliability stage for coupled state/event guarantees | Relay, recovery, idempotency and durable acceptance proven; infrastructure and producer rollout coordinated |
| W11 | Remove obsolete code/config/contracts; strengthen audit; update docs/CI | Full checks pass; all consumers accounted for; no duplicate implementations remain |

Some independent tests/hardening can run earlier, but do not begin a broad feature rewrite before request-scoped identity and state are established. Do not deploy outbox-producing code before its consumer infrastructure works.

### 18.2 Rollout safeguards

Work on a refactor branch based on the intended develop revision; do not overwrite concurrent changes or push directly to an automatically deployed branch as an incidental step.

Use additive, backward-readable state/token changes first. Keep a documented rollback revision and confirm that it can read any state produced by the candidate release. Do not label rollback safe solely because a previous container image exists.

Deploy development first and run real Alexa/event/worker checks there using authorised test identities. Compare response/error/latency/persistence-conflict and queue/worker metrics to the baseline. Define acceptable budgets from measured behaviour instead of inventing a performance guarantee.

If live backend or AWS access is unavailable, retain the exact externally blocked acceptance item in the status ledger. Complete independent code work and tests; do not claim deployment or device validation.

### 18.3 Required implementation report

For every work package, provide changed files, old behaviour/ownership, new ownership, preserved invariants, added/updated tests, command results, removed code, storage/API compatibility effects and remaining external blockers.

The file ledger must classify every tracked application/configuration/test/deployment file as modified, preserved with reason, removed with consumer evidence, or externally blocked. A new file discovered in the actual checkout is not exempt from the architecture rules because it was absent from this document's example map.

### 18.4 Definition of done

The work is complete only when feature dependencies are explicit, listener state is request/record scoped, models operate without Alexa/HTTP/database implementation knowledge, filters and payload identity have one owner, persistence failure cannot produce a false durable success, and the supported playback/dialogue/worker flows pass their behavioural tests.

It must also have no obsolete duplicate implementation left in production, no unsafe key/schema/token change, no silently dropped invalid worker records, no undocumented live-contract assumption and no claimed test/deployment result without execution evidence.

Clean architecture here means that a developer can locate a feature's input adapter, decision model, external client, state transition and response formatter without following a container or arbitrary dictionary through the entire application. A rearranged folder tree alone does not meet that standard.

## 19. Source and verification ledger

Code observations refer to the baseline commit stated at the top. The links below identify source evidence, not proof that the proposed changes are already implemented.

| Reference | Source |
|---|---|
| R1 | Pinned develop commit metadata and README: existing application/worker architecture and reminder removal |
| R2 | `.agents/skills/hear-architecture-refactor/SKILL.md`: existing project conventions and migration rules |
| R3 | `src/container.py`, `src/application.py`, `src/registry.py`: composition, driver selection and ordered registration |
| R4 | `src/models/user.py`, `src/middleware/persistence.py`, `src/database/dynamo_user.py`: current state gateway, load/save handling and scoped writes |
| R5 | `src/constants/state.py`: version, scopes, field defaults and non-persisted identity/profile fields |
| R6 | `src/alexa/runtime.py`, `main.py`, `src/controllers/play.py`, `src/models/search.py`: runtime, cached application, action construction and mixed model/platform responsibilities |
| R7 | `src/clients/resolver.py`: per-call identity and cache eligibility/key |
| R8 | `src/utils/filters.py`, `src/utils/search_payload.py`, `src/clients/hear.py`: existing filter/payload responsibilities |
| R9 | `src/clients/pool.py`: event-loop-keyed pool and upstream configuration |
| R10 | `src/services/events.py`: outbound IDs, JSON parsing and batch failure handling |
| R11 | Pinned Git trees for models, clients, services and utilities: existing module inventory |

Pinned repository source root:

```text
https://github.com/Techta-Labs-Ltd/hear-py/tree/6e138e2cb5a095c4cc0a856291430cf6a3b683fb
```

Official platform references consulted:

| Reference | Source | Constraint used |
|---|---|---|
| E1 | AWS Lambda best practices | Reusable infrastructure versus invocation-specific user data |
| E2 | Amazon AudioPlayer interface reference | Sessionless callbacks and request-specific response limits |
| E3 | Amazon request/response JSON reference | Envelope/session distinctions across request types |
| E4 | DynamoDB transaction APIs | Real atomic read/write operations and transaction idempotency |
| E5 | DynamoDB expired items and TTL | Expired items can remain readable until deletion |
| E6 | AWS transactional outbox guidance | Dual-write failure handling and duplicate-delivery considerations |
| E7 | AWS Lambda SQS error handling | Partial-batch failure and retry handling |

```text
E1 https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html
E2 https://developer.amazon.com/en-US/docs/alexa/custom-skills/audioplayer-interface-reference.html
E3 https://developer.amazon.com/en-US/docs/alexa/custom-skills/request-and-response-json-reference.html
E4 https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html
E5 https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ttl-expired-items.html
E6 https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html
E7 https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-errorhandling.html
```

The proposed class contracts, work packages, file ownership changes and test cases are engineering recommendations. The live Hear/Resolver OpenAPI and production deployment were not verified during preparation; endpoint removal or wire-format changes remain gated on those contracts and consumer evidence.
