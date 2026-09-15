# Universal User Recognition and Listener Sync Plan

## Objective

Make one class-based identity flow responsible for recognizing every Alexa
request, resolving its canonical Hear listener, loading the correct user state,
and providing the same identity pair to all Hear API calls.

The canonical identity pair is:

- `listenerId`: Hear's canonical listener identifier.
- `alexaUserId`: the current Alexa skill-scoped user alias and fallback key.

`listenerId` is authoritative when available. `alexaUserId` remains necessary
for a first request, resolver fallback, and API attribution.

## Non-negotiable rules

- `User` remains the only durable listener-state gateway.
- `Listener` composes `User` and exposes listener identity/profile behavior.
- `RequestContext` remains the only owner of request-lifetime identity data.
- No feature reads `listenerId` directly from a raw store or independently
  parses the Alexa envelope for a user ID.
- Identity resolution happens before persistence hydration.
- Profile PII, device IDs, resolver diagnostics, and reminder tokens are never
  persisted in DynamoDB.
- The codebase uses `/listeners/resolve` for lookup-only recognition and
  `/listeners/register` or `/listeners/sync` for canonical registration with
  permitted profile synchronization.

## Target class ownership

| Class | Responsibility |
| --- | --- |
| `IdentityContext` | Immutable, request-scoped representation of Alexa and Hear identity. |
| `IdentityPolicy` | Extracts valid identity signals from an Alexa request. |
| `ListenerIdentityService` | Calls Hear's resolver and returns an enriched `IdentityContext`. |
| `IdentityInterceptor` | Places the resolved identity in `RequestContext` and configures persistence. |
| `User` | Owns persistence-key selection, hydration, state validation, and serialization. |
| `Listener` | Provides the current identity and profile behavior through its injected `User`. |
| `ListenerSyncPayload` | Builds the registration/sync payload from the current `IdentityContext`. |
| `ListenerPayload` | Validates the strict live API allow-list before HTTP. |
| `ListenerSyncService` | Sends one validated sync payload and applies a returned `listenerId` only to request state. |

`User` must not become an Alexa-envelope parser. Keeping request parsing in
`IdentityPolicy` prevents transport details from leaking into durable-state
logic while preserving one universal identity flow.

## Request lifecycle

```text
Alexa request
  -> IdentityInterceptor captures alexaUserId and optional personId
  -> ListenerIdentityService resolves listenerId with Hear
  -> RequestContext stores IdentityContext
  -> User configures persistence with listenerId and alexaUserId fallback
  -> LoadPersistenceInterceptor hydrates User
  -> controllers/models use Listener.identity()
  -> outbound Hear calls receive listenerId + alexaUserId from IdentityContext
```

### Recognition rules

1. Read `context.System.user.userId` as the required Alexa user identity.
2. Read `context.System.person.personId` only when Alexa has recognized a
   speaker.
3. Treat a device ID as request context, never as proof of a person.
4. Send permitted profile email only after Alexa has granted the email scope.
5. Call `/listeners/resolve` before state loading.
6. On `400`, `401`, `403`, `409`, `429`, timeout, or network failure, keep the
   request working under its isolated `alexaUserId` persistence key.
7. Never manufacture, merge, or persist a canonical listener ID locally when
   the resolver did not return one.

## API contract cleanup

### Canonical resolution: `POST /listeners/resolve`

The resolver request is identity-only. Its permitted fields are:

```json
{
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "alexaUserId": "amzn1.ask.account.example",
  "userEmail": "listener@example.com"
}
```

The live resolver accepts only `listenerId`, `alexaUserId`, and `userEmail`.
At least one must be present. Device, person, skill, locale, environment,
principal-type, and client-version data remain request-local and are never
sent to this endpoint.

The only response field required by the skill is `listenerId`.

### Registration/sync: `POST /listeners/register` and `POST /listeners/sync`

Both endpoints use the same canonical registration transaction. Sync preserves
an existing listener ID. The payload builder must reject every field outside
this allow-list:

```json
{
  "action": "alexa",
  "alexaUserId": "amzn1.ask.account.example",
  "listenerId": "listener-7",
  "listenerName": "Alex Morgan",
  "email": "listener@example.com",
  "city": "Manchester",
  "latitude": 53.4808,
  "longitude": -2.2426
}
```

Rules:

- `action`, `alexaUserId`, and `listenerId` are always present; `listenerId`
  may be `null` for the first sync.
- Name and email are included only after their respective Alexa permissions
  have been granted and values have been retrieved during the request.
- City and coordinates are included only when available through the existing
  permitted location flow.
- Do not send device ID, skill ID, locale, environment, address, country,
  playback values, listening history, notifications, feature flags, or raw
  state.
- Reject invalid latitude/longitude rather than forwarding malformed values.

## Legacy removal

### Registration code

1. Keep `HearApiClient.register_listener` and `HearApiClient.sync_listener` on
   the same strict payload contract.
2. Reject unknown and malformed registration fields before making an HTTP call.
3. Replace `ListenerSyncSupport.build_listener_sync_profile` with the
   dedicated `ListenerSyncPayload` class so unknown input cannot reach the
   client.

### Identity duplication

1. Search all models, middleware, and services for direct calls to
   `AlexaRequest.get_user_id` and direct reads of `store["listenerId"]`.
2. Migrate outbound calls to a single `Listener` identity accessor that returns
   the request's `IdentityContext`.
3. Pass only its `listenerId` and `alexaUserId` to outbound attribution
   payloads.
4. Preserve `User.configure_persistence_identity` as the single persistence
   key decision point.
5. Remove obsolete aliases and compatibility wrappers once every caller has
   migrated.

### Reminder feature and permission

1. Remove `REMINDERS_READWRITE` from `config/permission_scopes.py`.
2. Delete `src/services/alexa_reminder.py`.
3. Remove reminder cancellation from playback, feedback, and launch workflow.
4. Remove `AlexaClient.cancel_feedback_reminder`.
5. Remove `feedbackReminderAlertToken` from `StateSchema`, the store schema,
   migrations, reset paths, and tests.
6. Remove reminder injection and construction from `ApplicationContainer`.
7. Remove the reminders permission from the Alexa Developer Console/skill
   manifest. The manifest is not present in this repository, so that is a
   separate deployment action.

## Implementation order

1. Add characterization tests for identity extraction, known listener
   resolution, first-time listener resolution, recognized-person resolution,
   resolver conflict/failure, and persistence fallback.
2. Introduce `ListenerSyncPayload` and make the sync service use it without
   changing endpoint behavior.
3. Apply the strict registration payload class to both `/listeners/register`
   and `/listeners/sync`.
4. Migrate every outbound identity caller to the `Listener` identity accessor.
5. Remove reminder code, scope, state fields, schemas, and tests.
6. Update API-contract documentation and any deployment manifest outside this
   repository.
7. Run the verification suite and remove only legacy data fields that are no
   longer referenced.

## Acceptance criteria

- Every request has one `IdentityContext` in `RequestContext` before
  persistence loading.
- A resolved listener uses a canonical persistence key; resolver failure uses
  only the Alexa user alias key.
- No feature independently chooses an identity or persistence key.
- `/listeners/sync` accepts and sends only allow-listed values.
- Both registration endpoints reject non-contract fields before an HTTP call.
- No reminder scope, reminder service, reminder API call, reminder state key,
  or reminder test remains.
- No PII, canonical listener ID, device ID, or reminder token is persisted.
- The strict architecture audit, Ruff, compile checks, and full test suite
  pass.

## Verification commands

```powershell
python -m ruff check src tests
python -m compileall -q main.py src config
python -m pytest -q
```
