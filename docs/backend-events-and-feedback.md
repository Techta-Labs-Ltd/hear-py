# Hear Alexa backend, identity, state, and event contract

Status: implementation contract, schema version 2
Audience: Hear backend, Alexa, data, moderation, notification, and operations teams

## 1. Decisions and ownership

The backend-provided `listenerId` is the canonical listener identity. Alexa identifiers are provider aliases and can change. There is no account-linking or OAuth flow in this project.

The backend is the source of truth for:

- canonical listener identity and alias matching;
- complete listening history and cumulative listening time;
- feedback and rating history;
- follows and unfollows;
- moderation reports;
- catalogue, creator, organisation, and publication data;
- recommendation and personalisation projections.

`HearListenerStateTable` is only short-lived Alexa execution state. It stores playback resume state, active dialogue state, onboarding/location state, and small bounded caches needed to make the voice flow work. It does not duplicate backend event history or profile PII. `HearNotificationInboxTable` is a separate backend-written delivery inbox; it is not listener profile/history state.

| Data | Authority | Alexa/DynamoDB use |
| --- | --- | --- |
| `listenerId` and identity aliases | Hear backend | `listenerId` is used in the DynamoDB key and attached to calls/events in memory |
| Full listening history | Hear backend event projection | DynamoDB keeps at most 20 compact recent subjects for exclusion and voice continuity |
| Feedback history | Hear backend `feedback.given` projection | DynamoDB keeps only up to 50 answered keys to suppress repeat prompts |
| Reports | Hear backend report projection | DynamoDB keeps only the active report dialogue |
| Follows | Hear backend follow projection | DynamoDB keeps a bounded 50-entry UX/search cache |
| Profile name/email/address | Alexa APIs and Hear backend | Request-local only; not written to DynamoDB |
| Catalogue metadata | Hear backend | Only the current/prepared playback item is retained locally |
| Content/publication notifications | Hear backend | Backend inserts a bounded inbox row; Alexa advances delivery/consumption status |

## 2. Request lifecycle

Every normal stateful Alexa request follows this sequence:

1. Capture the Lambda deadline and Alexa request identifiers.
2. Read `alexaUserId`, optional `personId`, `deviceId`, `skillId`, locale, and principal type.
3. Check the warm-Lambda identity cache.
4. If permitted and needed, read `Profile.email` from Alexa as an exact recovery signal.
5. Call `POST /alexa/listeners/resolve` to obtain the canonical `listenerId`.
6. Select DynamoDB key `listener:<environment>:<listenerId>`. If resolution is unavailable, isolate the request under the current `alexaUserId`.
7. Load the four scoped state items from `HearListenerStateTable`.
8. Run the requested dialogue, resolver, search, notification, playback, feedback, follow, or report workflow.
9. Persist only changed state scopes and omit default/empty values.
10. Publish domain events to SQS. The SQS worker forwards the unchanged envelope to the backend webhook.

`CanFulfillIntentRequest` remains stateless and skips canonical identity/persistence. Amazon API calls never receive `listenerId` or the Hear API key. Alexa `apiAccessToken` is never sent to Hear, DynamoDB, SQS, or logs.

## 3. Outbound dependency inventory

| Target | Operation | Authentication | Trigger |
| --- | --- | --- | --- |
| Hear API | `POST /alexa/listeners/resolve` | `X-Api-Key` | Identity-cache miss on a normal request |
| Hear API | `POST /alexa/listeners/sync` | `X-Api-Key` | Launch/profile synchronisation |
| Hear API | `POST /alexa/search` | `X-Api-Key` | Search, browse, queue continuation, playback lookup |
| Hear API | `POST /alexa/availability` | `X-Api-Key` | Local source discovery and source publication/track choice |
| Resolver | `POST /resolve` | `x-api-key` | Search/source/location interpretation |
| DynamoDB listener state | `GetItem`, `UpdateItem`, `DeleteItem` | Lambda IAM | Stateful request |
| DynamoDB notification inbox | `Query`, `GetItem`, `UpdateItem` | Lambda IAM | Launch, notification intent, and notification playback events |
| Login with Amazon | `POST /auth/o2/token` | Proactive client credentials | Cached worker token on notification inserts |
| Alexa proactive events | `POST /v1/proactiveEvents[/stages/development]` | LWA bearer token | Notification inbox stream `INSERT` |
| Amazon SQS | `SendMessage` | Lambda IAM | Playback, feedback, follow, unfollow, report |
| Hear webhook | `POST WEBHOOK_OUTBOUND_URL` | API key plus HMAC | SQS consumer delivery |
| Alexa directives | `POST /v1/directives` | Alexa bearer token | One best-effort progressive response |
| Alexa profile | `GET /v2/accounts/~current/settings/{setting}` | Alexa bearer token | Granted name/email permission |
| Alexa address | `GET /v1/devices/{id}/settings/address` | Alexa bearer token | Granted full-address permission |
| Alexa reminders | `DELETE /v1/alerts/reminders/{token}` | Alexa bearer token | Clear a saved feedback reminder |

## 4. Canonical listener registration and resolution

### 4.1 Request

~~~http
POST <HEAR_API_URL>/<HEAR_API_PATH_PREFIX>/listeners/resolve
X-Api-Key: <HEAR_API_KEY>
Content-Type: application/json
~~~

~~~json
{
  "alexaUserId": "amzn1.ask.account.current-alias",
  "personId": "amzn1.ask.person.optional",
  "deviceId": "amzn1.ask.device.current",
  "skillId": "amzn1.ask.skill.hear",
  "locale": "en-GB",
  "userEmail": "listener@example.com",
  "environment": "production",
  "principalType": "recognized_person",
  "clientVersion": "alexa-skill"
}
~~~

| Field | Required | Rule |
| --- | ---: | --- |
| `alexaUserId` | yes | Current skill-scoped Alexa alias |
| `personId` | no | Present when Alexa recognises a speaker |
| `deviceId` | no | Context only; never proof of identity |
| `skillId` | no | Namespace for Alexa aliases |
| `locale` | no | Current request locale |
| `userEmail` | no | Lower-cased exact email, only with granted Alexa permission |
| `environment` | yes | Deployment stage |
| `principalType` | yes | `recognized_person` or `skill_user` |
| `clientVersion` | yes | Alexa client contract identifier |

Machine-readable request and response contract: [`schemas/listener-identity-resolve.schema.json`](../schemas/listener-identity-resolve.schema.json).

### 4.2 Response

~~~json
{
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "listenerType": "registered",
  "created": false
}
~~~

Only `listenerId` is required by the skill. An obsolete generic `id` field is not accepted as a substitute.

### 4.3 Backend transaction

The endpoint must resolve or register a listener atomically:

1. Validate the API key and request.
2. Exact-match `(alexa_user, skillId, alexaUserId)`.
3. If supplied, exact-match `(alexa_person, skillId, personId)`.
4. If supplied, exact-match a normalized email using a unique keyed hash. Do not fuzzy-match email, name, device, or location.
5. If signals map to multiple listeners, return `409`, record an operator-visible conflict, and never merge automatically.
6. If one listener matches, attach newly observed exact aliases and update their `last_seen_at` values.
7. If none match, create one listener and its aliases in a single transaction.
8. Enforce unique identity constraints so concurrent first requests cannot create duplicates.

Recommended backend tables:

~~~text
listeners(id, listener_type, created_at, updated_at)
listener_identities(
  id, listener_id, provider, provider_subject_hash,
  encrypted_provider_subject, skill_id,
  first_seen_at, last_seen_at, revoked_at
)
~~~

Recommended providers are `alexa_user`, `alexa_person`, and `alexa_profile_email`. A device ID is not an identity provider.

On `400`, `401`, `403`, `409`, `429`, `5xx`, timeout, or network failure, the skill continues with an isolated Alexa alias key and records fallback metrics. Successful mappings are cached for `HEAR_IDENTITY_CACHE_TTL_MS`.

## 5. Listener profile synchronisation

This endpoint updates profile/context only. It must not append listening history, feedback, reports, or follows.

~~~http
POST <HEAR_API_URL>/<HEAR_API_PATH_PREFIX>/listeners/sync
X-Api-Key: <HEAR_API_KEY>
Content-Type: application/json
~~~

Common request fields are always present, although nullable values may be JSON `null`:

~~~json
{
  "alexaUserId": "amzn1.ask.account.current-alias",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "skillId": "amzn1.ask.skill.hear",
  "environment": "production",
  "principalType": "skill_user",
  "deviceId": "amzn1.ask.device.current",
  "apiEndpoint": "https://api.eu.amazonalexa.com",
  "locale": "en-GB",
  "listenerType": "registered",
  "clientVersion": "alexa-skill",
  "playbackSpeed": 1.25,
  "userName": "Alex Hear",
  "userEmail": "listener@example.com",
  "address": "Optional permitted address",
  "city": "Manchester",
  "state": "Greater Manchester",
  "country": "United Kingdom",
  "countryCode": "GB",
  "postalCode": "M1 1AA",
  "latitude": 53.4808,
  "longitude": -2.2426,
  "locality": "Manchester"
}
~~~

The protected fields from `userName` through `locality` are included only when the profile is classified as registered, currently requiring a permitted email and a permitted name. The response is:

~~~json
{"listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa"}
~~~

Removed from this contract: `listeningPattern`, `followedCreatorIds`, `followedOrganizationIds`, `playCount`, `lastPlayedAt`, `recentPlayedIds`, and `recentPlays`. The backend already derives these from canonical events; sending them on every launch caused duplicate ownership and growing payloads.

Machine-readable contract: [`schemas/listener-sync.schema.json`](../schemas/listener-sync.schema.json).

## 6. Resolver contract

~~~http
POST <HEAR_RESOLVER_URL>/resolve
x-api-key: <HEAR_API_KEY>
Content-Type: application/json
~~~

~~~json
{
  "utterance": "play pendle voice",
  "timezone": "Europe/London",
  "country_code": "gb",
  "alexaUserId": "amzn1.ask.account.current-alias",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa"
}
~~~

`utterance`, `timezone`, and `country_code` are required. The two identity fields are included when available. The skill consumes `status`, `intent`, `entities`, `slots`, `ambiguities`, and `timingMs`. Ambiguities may be grouped by phrase or returned as a flat candidate array; normalization accepts both shapes.

Machine-readable request contract: [`schemas/resolver-request.schema.json`](../schemas/resolver-request.schema.json).

## 7. Search contract

~~~http
POST <HEAR_API_URL>/<HEAR_API_PATH_PREFIX>/search
X-Api-Key: <HEAR_API_KEY>
Content-Type: application/json
~~~

~~~json
{
  "query": "local sport",
  "limit": 3,
  "page": 0,
  "alexaUserId": "amzn1.ask.account.current-alias",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "isLocal": true,
  "isRecommended": false,
  "sort": "nearest",
  "filter": {
    "contentIds": [],
    "creatorIds": [],
    "organizationIds": [],
    "publicationIds": [],
    "categorySlugs": ["sport"],
    "tags": [],
    "city": "Manchester",
    "countryCode": "GB",
    "isPublication": false,
    "latitude": 53.4808,
    "longitude": -2.2426,
    "publishedFrom": "2026-09-01",
    "publishedTo": "2026-09-03"
  }
}
~~~

Empty filters are omitted in real requests. Allowed sorts are `recommended`, `nearest`, `popular`, `latest`, and `trending`.

All listener-facing discovery and choice searches use pages of three. Every spoken
page starts again at first, second, and third, including pages reached through next
or previous. Dynamic Alexa entity synonyms are replaced with only the choices on
the current page. The response offers `show more` only when cached choices remain
or the API reports another page; it offers `previous` only after the first page.
Single-content lookups may use a limit of one because they do not produce a spoken
choice list.

The skill accepts result arrays from `results` or `items` and consumes top-level `total`, `totalPages`, `page`, `client_message`, `search_relaxation`, and `session_key`. A playable item can contain:

- `contentId` or `id`, title/spoken title, summary, category/tags;
- creator and organisation IDs/names;
- `audioUrl`, duration, and playback-speed variants;
- publication ID/title, track index/count, and publication membership;
- locality/location metadata needed for spoken context.

Machine-readable request contract: [`schemas/search-request.schema.json`](../schemas/search-request.schema.json).

### 7.1 Alexa availability bridge

Availability is a small catalogue-summary endpoint. It tells the voice client which
choices to offer; it does not return playable audio and it does not replace
`/alexa/search`.

~~~http
POST <HEAR_API_URL>/<HEAR_API_PATH_PREFIX>/availability
X-Api-Key: <HEAR_API_KEY>
Content-Type: application/json
~~~

Location request:

~~~json
{
  "filter": {
    "location": {
      "city": "Swindon",
      "latitude": 51.56,
      "longitude": -1.78
    }
  },
  "page": 0,
  "limit": 3
}
~~~

Location response:

~~~json
{
  "page": 0,
  "limit": 3,
  "total": 2,
  "totalPages": 1,
  "remaining": 0,
  "hasMore": false,
  "nextPage": null,
  "organizations": [
    {"id": "706cb68b-8059-407e-a696-0651018066cd", "name": "Talking News Federation"}
  ],
  "creators": [
    {"id": "4cd2cb60-1314-4f66-841d-e49ed4820a3b", "name": "Adeshina Ayomide"}
  ]
}
~~~

After the listener chooses a source, the skill sends exactly one of these filters:

~~~json
{
  "filter": {"creatorId": "4cd2cb60-1314-4f66-841d-e49ed4820a3b"},
  "page": 0,
  "limit": 3
}
~~~

~~~json
{
  "filter": {"organizationId": "706cb68b-8059-407e-a696-0651018066cd"},
  "page": 0,
  "limit": 3
}
~~~

Source response:

~~~json
{
  "page": 0,
  "limit": 3,
  "total": 5,
  "totalPages": 1,
  "remaining": 0,
  "hasMore": false,
  "nextPage": null,
  "publicationCount": 5,
  "standaloneTrackCount": 8,
  "publications": [
    {
      "publicationId": "b7f65f28-5ba0-4775-b4a1-8a58d821eff5",
      "title": "Morning Briefings",
      "trackCount": 31,
      "publishedAt": 1788518929,
      "updatedAt": 1788518929
    }
  ]
}
~~~

The skill follows these rules:

1. A location response becomes a paged spoken list of organisations and creators.
2. A source with publications and standalone tracks prompts for publications or tracks.
3. A source with publications only goes directly to the publication choices.
4. A source with no publications goes silently to `/alexa/search`, filtered by the selected creator or organisation and `isPublication: false`.
5. Choosing tracks calls `/alexa/search` with the source filter and `isPublication: false`; choosing a track then performs a `contentIds` lookup.
6. Choosing a publication performs a `publicationIds` lookup through `/alexa/search`.
7. Availability and track-choice requests use a limit of three. Each page is spoken as first, second, and third, and supports names, ordinals, next, and previous. The skill offers more choices only when another API page exists.
8. A timeout, non-2xx response, invalid response, or empty location choice list falls back to the existing search flow without announcing an availability error.

The availability request intentionally carries no listener identity, profile data,
utterance, or playback history. The source IDs and coordinates already supplied by
the catalogue or resolver are sufficient for this bridge.

## 8. DynamoDB V2 state contract

### 8.1 Table and keys

`HearListenerStateTable` has composite key:

~~~text
PK id    = listener:<environment>:<listenerId>
SK scope = CORE | PLAYBACK | DIALOG | CACHE
~~~

Each item has this physical shape:

~~~json
{
  "id": "listener:production:6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "scope": "PLAYBACK",
  "attributes": {
    "activePlayback": {
      "contentId": "content-1",
      "audioUrl": "https://cdn.hear.media/content-1.mp3",
      "offsetMs": 42000,
      "status": "paused"
    }
  },
  "schemaVersion": 2,
  "stateVersion": 9,
  "expiresAt": 1804000000
}
~~~

Actual fields are routed as follows:

| Scope | Fields | TTL |
| --- | --- | --- |
| `CORE` | locality, coordinates, city/postcode/country code, location timestamps/source, playback speed, play/launch counts, first/last launch, onboarding state/counters, listener type, profile retry timestamps | 180 days |
| `PLAYBACK` | `activePlayback`, `playbackQueue`, `preparedNextContent` | 30 days |
| `DIALOG` | `activeDialog`, feedback/report/follow/resume/location/search/ambiguity/latest-source prompt context and flags | 24 hours, or later active-dialog expiry |
| `CACHE` | compact play history, compact feedback candidates/progress/answered keys, followed-source cache, listening pattern, last-completed/latest-source markers | 90 days |

Defaults, `null`, `false`, empty lists, and empty maps are omitted. Clearing a value uses DynamoDB `REMOVE`; it is not stored as `NULL`.

### 8.2 Deliberately not persisted

- `listenerId` because it is already represented by the partition key and resolved each request;
- profile PII: email, names, full address, state, and country;
- `feedbackHistory` and `reportHistory`;
- large browse catalogues and pending result item arrays;
- derived current-content fields, `lastToken`, `lastOffsetMs`, `timeSpentHours`, subject IDs/types, and speed aliases that can be rebuilt from canonical playback state;
- Alexa device IDs, reminder tokens, deferred request data not required by an active dialog, and raw access tokens.

Active playback stores only the fields needed to resume and interpret events. Recent local play history is capped at 20 and drops URLs, summaries, nested session ledgers, and nested publication track maps. Feedback candidates are capped at 5; answered keys at 50; followed sources at 50; publication progress at 2 publications and 100 compact tracks each.

### 8.3 Read/write and concurrency rules

- `PLAYBACK` and `DIALOG` use strongly consistent reads; `CORE` and `CACHE` use eventually consistent reads.
- Only scopes containing changed fields are written.
- Every scope has an independent `stateVersion`, preventing a dialogue update from conflicting with an AudioPlayer update.
- Writes condition on the loaded version. On conflict, the scope is re-read and retried with exponential backoff.
- Counters merge by delta; keyed caches merge by stable key; older playback timestamps cannot overwrite newer playback state.
- A scope warns at 65,536 bytes and is rejected before DynamoDB at 350,000 bytes, leaving headroom below DynamoDB's 400 KB item limit.
- The table uses on-demand billing, server-side encryption, point-in-time recovery, TTL, and retained deletion/update policies.
- Application access is point-key only. Do not add scans to request paths.

### 8.4 Canonical listener-key copy

`HearListenerStateTable` is the only listener-state table. The canonical key is
`listener:<environment>:<listenerId>`. When that key has no scoped items, the
skill may read the current Alexa-user alias from the same table once and copy
its sparse state to the canonical key. This keeps a listener stable when Alexa
changes the Alexa user ID without retaining or reading a second table.

An explicit listener-state deletion removes all four scoped items for the
selected key.

### 8.5 Backend-written notification inbox

`HearNotificationInboxTable` is deliberately separate from listener state. The
Hear backend owns notification eligibility and writes one row directly to this
table when an opted-in listener has a new single recording or publication. The
Alexa Lambda does not copy catalogue notifications into `CORE`, `CACHE`, or a
history array.

~~~text
PK listenerId     = canonical Hear listener ID
SK notificationId = stable, idempotent notification ID
GSI ActiveByListener:
  PK activeListenerId
  SK activePublishedAt = zero-padded publishedAt#notificationId
~~~

The backend should use a conditional put such as
`attribute_not_exists(notificationId)` and a deterministic ID (for example
`content:<contentId>` or `publication:<publicationId>`). This makes retries
idempotent and ensures that the DynamoDB stream produces only one `INSERT` for
proactive delivery. Do not delete and recreate a row to retry delivery.

Single-recording example:

~~~json
{
  "schemaVersion": 1,
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "notificationId": "content:content-1",
  "notificationType": "content",
  "contentId": "content-1",
  "title": "Morning bulletin",
  "creatorId": "creator-1",
  "creatorName": "Pendle Voice",
  "organizationId": "organisation-1",
  "organizationName": "Pendle Voice",
  "alexaUserId": "amzn1.ask.account.current-alias",
  "locale": "en-GB",
  "publishedAt": 1788451200,
  "status": "pending",
  "deliveryStatus": "pending",
  "sendProactive": true,
  "activeListenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "activePublishedAt": "00000000001788451200#content:content-1",
  "expiresAt": 1789056000
}
~~~

For a publication, set `notificationType` to `publication`, replace
`contentId` with `publicationId`, and make the stable ID
`publication:<publicationId>`. Exactly one of `contentId` and `publicationId`
is allowed. The machine-readable write contract is
[`schemas/notification-inbox-item.schema.json`](../schemas/notification-inbox-item.schema.json).

The backend must write the current Alexa alias associated with the canonical
listener because Amazon proactive unicast delivery requires it. A changed
Alexa alias is first attached through `/alexa/listeners/resolve`; future rows
must use that latest active alias. This alias is delivery routing data, not the
canonical identity.

User-consumption and transport delivery are separate state machines:

~~~text
User:     pending -> offered -> resolving -> queued -> consumed
                         |          |             |
                         +-> dismissed/unavailable
                                    +-> pending on temporary lookup/playback failure

Delivery: pending -> sent | suppressed | failed
                  -> retrying -> sent | failed | dead-letter queue
~~~

The active GSI keys remain only for `pending`, `offered`, `resolving`, and
`queued`; the skill removes them when a row becomes `consumed`, `dismissed`, or
`unavailable`. TTL is cleanup only, so reads also reject expired rows. The
backend should bound creation and retention per listener; the skill asks for
the newest item and mentions when additional active items exist.

Backend IAM should be least privilege: `dynamodb:PutItem` (and optionally
`DescribeTable`) on the environment-specific inbox table. The skill and stream
worker own `Query`/`GetItem`/`UpdateItem`. The CloudFormation outputs
`NotificationInboxTableName` and `NotificationInboxTableArn` are the deployment
handoff to the backend stack.

## 9. Domain event transport

### 9.1 Envelope V2

~~~json
{
  "event": "playback.finished",
  "schemaVersion": 2,
  "eventId": "publication:publication-1:queue-1:finished:1788451200000",
  "timestamp": "2026-09-03T16:00:00Z",
  "data": {
    "alexaUserId": "amzn1.ask.account.current-alias",
    "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
    "clientEventId": "publication:publication-1:queue-1:finished:1788451200000"
  }
}
~~~

`eventId` equals `data.clientEventId` for all normal domain events. Backend consumers must deduplicate on `eventId` and ignore unknown fields. Machine-readable envelope: [`schemas/backend-event.schema.json`](../schemas/backend-event.schema.json).

SQS message attributes, when non-empty, are `eventType`, `eventId`, `schemaVersion`, `listenerId`, `subjectType`, `subjectId`, `publicationId`, and `notificationSubjectType`.

The webhook receives the exact compact SQS body with:

~~~http
Content-Type: application/json
X-Api-Key: <HEAR_API_KEY>
x-webhook-timestamp: <unix-seconds>
x-webhook-signature: t=<unix-seconds>,v1=<hex-hmac-sha256>
~~~

The signature input is `<timestamp>.<exact-request-body>`. Delivery is at least once and unordered. Partial batch failure retries only failed records; after five receives the message moves to the 14-day dead-letter queue. Backend `2xx` responses acknowledge delivery, including duplicate events already accepted.

### 9.2 Event catalogue

| Family | Event names |
| --- | --- |
| Playback | `playback.started`, `progress`, `nearly_finished`, `paused`, `resumed`, `stopped`, `finished`, `failed`, `cancelled` (all prefixed `playback.`) |
| Feedback | `feedback.given` |
| Follow | `user.followed_creator`, `user.unfollowed_creator`, `user.followed_organization`, `user.unfollowed_organization` |
| Report | `user.reported_content`, `user.reported_creator` |
| Notification preference | `notifications.enabled`, `notifications.disabled` |

## 10. Complete event data contracts

### 10.1 Playback

All playback event data can contain:

| Field | Meaning |
| --- | --- |
| `alexaUserId`, `listenerId` | Current alias and canonical listener |
| `subjectType`, `subjectId` | Canonical owner: content or publication |
| `creatorId`, `queueId` | Optional source/queue context |
| `sessionId` | Current track/listen session |
| `subjectSessionId` | Stable publication or standalone subject session |
| `eventType` | Suffix such as `started`, `progress`, or `finished` |
| `positionMs`, `durationMs`, `listenedMs` | Playback cursor/duration/high-water values |
| `timeSpentMs`, `timeSpentHours` | Measured listening time for this session |
| `completionPercentage` | Derived high-water percentage when duration is known |
| `timestampMs` | Event time in Unix milliseconds |
| `clientEventId` | `<subjectSessionId>:<eventType>:<timestampMs>` |

Standalone content adds `contentId`.

Publication playback adds `publicationId`, `trackContentId`, `trackIndex`, `trackCount`, `publicationTimeSpentMs`, `publicationTimeSpentHours`, and `trackListening`. `contentId` is deliberately omitted at the top level for a publication event; the current track is `trackContentId`.

The backend must upsert a playback session by `clientEventId`/`sessionId`. For cumulative time, apply only positive deltas:

~~~text
delta = max(0, incoming.timeSpentMs - stored_session.timeSpentMs)
stored_session.timeSpentMs = max(stored_session.timeSpentMs, incoming.timeSpentMs)
listener_subject.totalTimeSpentMs += delta
~~~

Do not sum repeated snapshots, retries, seek distances, or `timeSpentHours`.

### 10.2 Feedback

`feedback.given` data:

| Field | Rule |
| --- | --- |
| `alexaUserId`, `listenerId` | Identity |
| `feedbackKey` | Stable prompt-suppression key |
| `subjectType`, `subjectId` | Content/publication owner |
| `title`, `publicationTitle` | Optional display/spoken context |
| `creatorId`, `creatorName` | Optional creator context |
| `organizationId`, `organizationName` | Optional organisation context |
| `category` | Optional category context |
| `listenedMs`, `timeSpentMs`, `timeSpentHours` | Optional listening snapshot |
| `feedback` | `enjoyed`, `somewhat`, `not_enjoyed`, or `skipped` |
| `coverage`, `expectedTrackCount`, `meaningfulTrackCount` | Optional publication qualification data |
| `trackListening` | Publication-only compact track snapshots |
| `timestamp` | Unix milliseconds |
| `clientEventId` | `feedback:<listener-or-alexa>:<feedbackKey-or-subjectId>:<feedback>` |

Standalone feedback adds `contentId` and optional `parentPublicationId`. Publication feedback adds `publicationId` and unique ordered `contentIds`. The backend is the only full feedback-history store.

### 10.3 Follow and unfollow

All four follow events contain:

~~~json
{
  "alexaUserId": "amzn1.ask.account.current-alias",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "sourceType": "organization",
  "sourceId": "organization-1",
  "sourceName": "York Talking News",
  "notificationSubjectType": "publication",
  "timestamp": 1788451200000,
  "clientEventId": "follow:6fd214d5-49d4-42f7-a982-a56cd16c9baa:follow:organization:organization-1"
}
~~~

The event name says whether this is follow/unfollow and creator/organisation. Backend updates must be idempotent sets, not append-only duplicate rows.

`notificationSubjectType=publication` is the backend signal that a followed
source can produce new-publication updates. The backend applies the listener's
notification preference and writes eligible updates to the dedicated inbox in
section 8.5. It must never write them into `HearListenerStateTable`.

### 10.4 Notification preference

`notifications.enabled` and `notifications.disabled` contain:

~~~json
{
  "alexaUserId": "amzn1.ask.account.current-alias",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "enabled": true,
  "permissionGranted": true,
  "timestamp": 1788451200000,
  "clientEventId": "notifications:6fd214d5-49d4-42f7-a982-a56cd16c9baa:enabled:1788451200000"
}
~~~

The backend owns the durable preference. `enabled` is the user's Hear setting;
`permissionGranted` reports the Alexa notification scope visible on that
request. Disabling Hear notifications does not revoke an Alexa permission, so
the two fields can legitimately be `false` and `true`. Event IDs include the
timestamp because a listener can disable and later re-enable notifications.
On disable, the backend stops new writes and may dismiss still-active inbox
rows. No notification preference or catalogue subscription list is copied into
listener-state DynamoDB.

### 10.5 Reports

`user.reported_content` and `user.reported_creator` contain:

~~~json
{
  "alexaUserId": "amzn1.ask.account.current-alias",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "subjectType": "content",
  "subjectId": "content-1",
  "subjectName": "Morning bulletin",
  "contentId": "content-1",
  "publicationId": null,
  "recordedAt": 1788451200000,
  "status": "pending",
  "reason": "reported_via_alexa",
  "clientEventId": "alexa-report:6fd214d5-49d4-42f7-a982-a56cd16c9baa:content:content-1"
}
~~~

Nulls are removed from the emitted payload. Reports are stored only by the backend; DynamoDB does not keep `reportHistory`.

## 11. Alexa-owned API calls

### 11.1 Progressive response

~~~http
POST <apiEndpoint>/v1/directives
Authorization: Bearer <apiAccessToken>
Content-Type: application/json
~~~

~~~json
{
  "header": {"requestId": "Alexa request ID"},
  "directive": {
    "type": "VoicePlayer.Speak",
    "speech": "<speak>I'm finding something for you.</speak>"
  }
}
~~~

It is best-effort, sent at most once for a Launch/Intent request, and never changes the final response.

### 11.2 Profile and location

All Alexa reads use `Authorization: Bearer <apiAccessToken>` and `Accept: application/json`.

- `Profile.name` and `Profile.email` use `GET /v2/accounts/~current/settings/{setting}`.
- Full address uses `GET /v1/devices/{deviceId}/settings/address`.
- Geolocation is read from the Alexa request envelope and is not a separate HTTP call.

Responses `401/403` are permission/authorization failures, `204` is empty, and temporary failures are fail-open. Raw access tokens, raw full API responses, and raw email values are not logged.

### 11.3 Reminder deletion

~~~http
DELETE <apiEndpoint>/v1/alerts/reminders/<alertToken>
Authorization: Bearer <apiAccessToken>
~~~

Deletion is best-effort. Reminder tokens are no longer durable DynamoDB fields.

### 11.4 Alexa proactive event delivery

An inbox `INSERT` invokes `main.notification_handler` through the DynamoDB
stream. The worker obtains a client-credentials token using scope
`alexa::proactive_events`, caches it for its safe lifetime, then posts an
`AMAZON.MediaContent.Available` event to the European Alexa endpoint. Development
uses `/v1/proactiveEvents/stages/development`; production uses
`/v1/proactiveEvents/`. A successful request returns `202`.

The exact outbound shape is:

~~~json
{
  "timestamp": "2026-09-03T16:00:00Z",
  "referenceId": "sha256-of-notification-id",
  "expiryTime": "2026-09-03T22:00:00Z",
  "event": {
    "name": "AMAZON.MediaContent.Available",
    "payload": {
      "availability": {
        "startTime": "2026-09-03T16:00:00Z",
        "provider": {"name": "localizedattribute:providerName"},
        "method": "STREAM"
      },
      "content": {
        "name": "localizedattribute:contentName",
        "contentType": "EPISODE"
      }
    }
  },
  "localizedAttributes": [{
    "locale": "en-GB",
    "providerName": "Pendle Voice",
    "contentName": "Morning bulletin"
  }],
  "relevantAudience": {
    "type": "Unicast",
    "payload": {"user": "amzn1.ask.account.current-alias"}
  }
}
~~~

HTTP `429`, `432`, `500`, and `503`, plus network failures, are retryable.
Lambda reports only the failed DynamoDB sequence number; after five retries the
record is sent to `ProactiveNotificationDeadLetterQueue`. Other rejection
statuses are recorded as terminal delivery failures. Status-only `MODIFY`
events do not trigger another send.

The Alexa skill manifest must request the Notifications permission and publish
the proactive schema:

~~~json
{
  "permissions": [{"name": "alexa::devices:all:notifications:write"}],
  "events": {
    "publications": [
      {"eventName": "AMAZON.MediaContent.Available"}
    ]
  }
}
~~~

This is an Alexa capability permission, not account linking. There is no
account-linking or Hear OAuth step.

## 12. Backend implementation plan

### P0: required before enabling canonical identity everywhere

- Implement the atomic `/alexa/listeners/resolve` transaction and unique alias constraints.
- Accept event envelope V2 and deduplicate on `eventId`.
- Persist raw event receipts before updating projections.
- Project playback, feedback, follow, and report events into backend-owned tables.
- Project notification preference events and enforce them before writing an inbox row.
- Keep accepting the legacy V1 event envelope only for the agreed deployment window.
- Return `2xx` for duplicate event IDs and retryable `5xx` only for genuine ingestion failures.

### P1: deployment

- Deploy `HearListenerStateTable` as the sole listener-state table and grant the skill access only to it.
- Deploy the skill with `HEAR_DDB_TABLE` set to `HearListenerStateTable`.
- Deploy `HearNotificationInboxTable` separately, grant the backend conditional `PutItem`, and pass its stack output to the backend deployment.
- Configure environment-specific proactive LWA credentials and the Alexa manifest permission/publication.
- Enable canonical identity in development, run changed-alias/same-email and person-ID tests, then promote to production.
- Monitor identity latency/alias-copy/conflict rate, conditional conflicts by scope, item sizes, event age, webhook retries, and DLQ depth.

### P2: backend personalisation hardening

- Build listener-subject history from playback events rather than listener-sync snapshots.
- Build feedback, moderation, and follow tables from their events.
- Personalise `/alexa/search` by `listenerId`; do not require the skill to upload history on launch.
- Optionally return a compact backend-owned preference/follow snapshot from a dedicated endpoint if Alexa needs cross-device cache repair.
- Add retention/deletion jobs for raw event receipts and provider identity data under the product privacy policy.

### Acceptance checks

- A known Alexa alias or recognised person resolves to the existing `listenerId`.
- A changed Alexa alias with the same exact permitted email can recover the listener.
- Conflicting exact signals return `409` and never auto-merge.
- Every normal Hear request and domain event carries `listenerId` when resolution succeeds.
- Search/resolver still work in isolated fallback mode when identity is unavailable.
- A feedback/report retry creates one backend record.
- Listening time is not inflated by retries, seeks, compact local history, or duplicate snapshots.
- No listener sync contains history, follow lists, feedback, or report data.
- No DynamoDB item contains profile email/name/address, full feedback/report history, raw catalogue results, or Alexa tokens.
- V2 writes touch only changed scopes and default values are removed rather than stored as `NULL`.
- A repeated backend notification write does not produce a second row or proactive event.
- A single-content row searches by `contentId`; a publication row searches by `publicationId`.
- Inbox rows become `consumed` only after `AudioPlayer.PlaybackStarted`, and temporary playback failure returns them to `pending`.
- Disabling notifications stops future backend writes without requiring account linking.

## 13. Logging and privacy rules

- Log operation, route, status, latency, retry number, request ID, event type/ID, and safe field/key presence.
- Do not log raw Alexa access tokens, API keys, email, full address, coordinates, full utterances, audio URLs, or complete payload bodies containing personal data.
- Resolver diagnostics may log normalized entity metadata and slot structure without coordinates; production should prefer an utterance hash/length over raw text.
- DynamoDB logs may include scope, version, size, conflict count, and a one-way key correlation hash, never the full partition key or attributes.
- Sentry and CloudWatch should use request/event correlation IDs and must not attach listener PII.

## 14. Source-of-truth files

- `src/services/listener_identity.py`
- `src/services/listener_sync.py`
- `src/utils/search_payload.py`
- `src/clients/resolver.py`
- `src/utils/events.py`
- `src/services/events.py`
- `src/constants/state.py`
- `src/database/dynamo_user.py`
- `src/database/notification_inbox.py`
- `src/models/notifications.py`
- `src/services/notification_delivery.py`
- `src/clients/proactive.py`
- `schemas/listener-identity-resolve.schema.json`
- `schemas/listener-sync.schema.json`
- `schemas/resolver-request.schema.json`
- `schemas/search-request.schema.json`
- `schemas/backend-event.schema.json`
- `schemas/notification-inbox-item.schema.json`
