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

`HearListenerStateTable` is only short-lived Alexa execution state. It stores playback resume state, active dialogue state, onboarding/location state, and small bounded caches needed to make the voice flow work. It does not duplicate backend event history, notification documents, or profile PII.

| Data | Authority | Alexa/DynamoDB use |
| --- | --- | --- |
| `listenerId` and identity aliases | Hear backend | `listenerId` is used in the DynamoDB key and attached to calls/events in memory |
| Full listening history | Hear backend event projection | DynamoDB keeps at most 20 compact recent subjects for exclusion and voice continuity |
| Feedback history | Hear backend `feedback.given` projection | DynamoDB keeps only up to 50 answered keys to suppress repeat prompts |
| Reports | Hear backend report projection | DynamoDB keeps only the active report dialogue |
| Follows | Hear backend follow projection | DynamoDB keeps a bounded 50-entry UX/search cache |
| Profile name/email/address | Alexa APIs and Hear backend | Request-local only; not written to DynamoDB |
| Catalogue metadata | Hear backend | Only the current/prepared playback item is retained locally |
| Content/publication notifications | Hear notification API | Alexa fetches and updates them with `POST /alexa/notification` |

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
| Hear API | `POST /alexa/notification` | `X-Api-Key` | Notification fetch, user status, and delivery status |
| Login with Amazon | `POST /auth/o2/token` | Proactive client credentials | Cached worker token on SQS notification messages |
| Alexa proactive events | `POST /v1/proactiveEvents[/stages/development]` | LWA bearer token | Notification SQS message |
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

The request contains only listener identity and permitted profile values:

~~~json
{
  "action": "alexa",
  "alexaUserId": "amzn1.ask.account.current-alias",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "listenerName": "Alex Hear",
  "email": "listener@example.com",
  "city": "Manchester",
  "longitude": -2.2426,
  "latitude": 53.4808
}
~~~

`action` and `alexaUserId` are always present. `listenerId` may be null on the
first sync. `listenerName`, `email`, and available location fields are included
only when permitted name and email have been resolved. The response is:

~~~json
{"listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa"}
~~~

Not sent: device, skill, environment, principal, locale, playback setting,
address, country, client-version, history, follows, feedback, or report data.

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

Empty filters are omitted in real requests. Allowed search sorts are `nearest`,
`popular`, `latest`, and `trending`. Recommendations are source discovery and
use `/alexa/availability`, never `/alexa/search`.
The search contract contains neither `isLocal` nor `isRecommended`. Local
catalogue searches use `sort: "nearest"` with listener identity or filter
coordinates.

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

Availability is the recommendation, local-source, and catalogue-summary endpoint.
It returns ordered creator and organisation choices for recommendation and local
requests, then reports publication and standalone-track inventory for the source
the listener selects. It does not return playable audio.

Trending requests remain on `/alexa/search` with `sort: "trending"`.

~~~http
POST <HEAR_API_URL>/<HEAR_API_PATH_PREFIX>/availability
X-Api-Key: <HEAR_API_KEY>
Content-Type: application/json
~~~

Machine-readable request contract:
[`schemas/availability-request.schema.json`](../schemas/availability-request.schema.json).

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

1. Local and recommendation responses become a paged spoken list of organisations and creators.
2. Trending calls `/alexa/search` and presents playable content in trending order.
3. A source with publications and standalone tracks prompts for publications or tracks.
4. A source with publications only goes directly to the publication choices.
5. A source with no publications goes silently to `/alexa/search`, filtered by the selected creator or organisation and `isPublication: false`.
6. Choosing tracks calls `/alexa/search` with the source filter and `isPublication: false`; choosing a track then performs a `contentIds` lookup.
7. Choosing a publication performs a `publicationIds` lookup through `/alexa/search`.
8. Availability and track-choice requests use a limit of three. Each page is spoken as first, second, and third, and supports names, ordinals, next, and previous. The skill offers more choices only when another API page exists.
9. A timeout, non-2xx response, invalid response, or empty source list does not trigger an unrestricted search or playback.

Availability carries `alexaUserId` and `listenerId` when available. The backend
uses canonical listener location for recommendations and canonical publication
history to keep unheard publications above heard publications without excluding
either group.

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

### 8.5 Notification API

The Alexa skill does not persist notification documents. Both spoken inbox
reads and proactive delivery use one authenticated endpoint:

~~~http
POST <HEAR_API_URL>/<HEAR_API_PATH_PREFIX>/notification
X-Api-Key: <HEAR_API_KEY>
Content-Type: application/json
~~~

Inbox reads use only the canonical listener ID:

~~~json
{
  "operation": "fetch",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "purpose": "inbox",
  "limit": 5
}
~~~

An SQS delivery fetch additionally includes the exact `notificationId` and sets
`purpose` to `delivery`. The response joins the source update to a transient
Alexa target:

~~~json
{
  "notification": {
    "schemaVersion": 1,
    "notificationId": "creator-update-18-20260910T150500Z",
    "notificationType": "creator_update",
    "sourceType": "creator",
    "sourceId": "creator-18",
    "sourceName": "Jordan Lee",
    "lastDate": "2026-09-10T15:05:00Z",
    "expiresAt": "2026-09-11T15:05:00Z"
  },
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "deliveryTarget": {
    "type": "alexa",
    "userId": "amzn1.ask.account.current-alias"
  }
}
~~~

The only notification types are `creator_update` and `organization_update`.
There is no track or publication payload. The machine-readable source-update
contract is
[`schemas/notification-item.schema.json`](../schemas/notification-item.schema.json).

Status changes use the same endpoint with `operation=update`. User status uses
`status`; proactive delivery uses `deliveryStatus`, optional
`deliveryHttpStatus`, and optional `deliveryErrorCode`.

User-consumption and transport delivery are separate state machines:

~~~text
User:     pending -> offered -> resolving -> queued -> consumed
                         |          |             |
                         +-> dismissed/unavailable
                                    +-> pending on temporary lookup/playback failure

Delivery: pending -> sent | suppressed | failed
                  -> retrying -> sent | failed | SQS dead-letter queue
~~~

The proactive worker receives only `schemaVersion`, `notificationId`, and
`listenerId` from SQS. It fetches the Alexa target using those IDs, sends the
event, and posts the outcome using `notificationId + listenerId`. Alexa user ID
is never a lookup filter or SQS field. Notification data is never written to
`HearListenerStateTable`.

The SQS body contract is
[`schemas/notification-delivery-message.schema.json`](../schemas/notification-delivery-message.schema.json).

## 9. Domain event transport

### 9.1 Envelope V3

~~~json
{
  "event": "playback.finished",
  "schemaVersion": 3,
  "eventId": "publication:publication-1:queue-1:finished:1788451200000",
  "timestamp": "2026-09-03T16:00:00Z",
  "data": {
    "action": "alexa",
    "alexaUserId": "amzn1.ask.account.current-alias",
    "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
    "clientEventId": "publication:publication-1:queue-1:finished:1788451200000"
  }
}
~~~

`eventId` equals `data.clientEventId` for all normal domain events. Backend consumers must deduplicate on `eventId` and ignore unknown fields. Machine-readable envelope: [`schemas/backend-event.schema.json`](../schemas/backend-event.schema.json).

SQS message attributes, when non-empty, are `eventType`, `eventId`,
`schemaVersion`, `action`, `listenerId`, `subjectType`, `contentId`,
`publicationId`, `sourceType`, `sourceId`, and `notificationSubjectType`.

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
| Playback | `playback.started`, `progress`, `nearly_finished`, `paused`, `resumed`, `stopped`, `finished`, `failed` (all prefixed `playback.`) |
| Feedback | `feedback.given` |
| Follow | `user.followed_creator`, `user.unfollowed_creator`, `user.followed_organization`, `user.unfollowed_organization` |
| Report | `user.reported_content`, `user.reported_creator` |
| Notification preference | `notifications.enabled`, `notifications.disabled` |

## 10. Complete event data contracts

### 10.1 Playback

All playback event data can contain:

| Field | Meaning |
| --- | --- |
| `action` | Always `alexa` |
| `alexaUserId`, `listenerId` | Current alias and canonical listener |
| `subjectType` | `content` or `publication` |
| `contentId` | The current playable track; always present |
| `publicationId` | The containing publication; publication playback only |
| `sessionId` | Current track/listen session |
| `subjectSessionId` | Stable publication or standalone subject session |
| `eventType` | Suffix such as `started`, `progress`, or `finished` |
| `positionMs`, `durationMs`, `listenedMs` | Playback cursor/duration/high-water values |
| `timeSpentMs` | Measured listening time for this session |
| `trackIndex`, `trackCount` | Optional publication position and size |
| `timestampMs` | Event time in Unix milliseconds |
| `clientEventId` | `<subjectSessionId>:<eventType>:<timestampMs>` |

For publication playback, `contentId` is still the current track and
`publicationId` is its container. Version 3 does not send `subjectId`,
`trackContentId`, hours, completion percentages, publication totals, or the full
`trackListening` array on every callback. The complete examples and exact ID
rules are in [Alexa outbound event contracts](alexa-event-contracts.md).

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
| `action` | Always `alexa` |
| `alexaUserId`, `listenerId` | Identity |
| `subjectType` | `content` or `publication` |
| `contentId` | Required for content feedback only |
| `publicationId` | Required for publication feedback only |
| `feedback` | `enjoyed`, `somewhat`, `not_enjoyed`, or `skipped` |
| `trackListening` | Publication-only per-track measurements keyed by `contentId` |
| `timestampMs` | Unix milliseconds |
| `clientEventId` | Stable feedback event identifier |

Titles, names, category, coverage counters, duplicate ID arrays, hours, and
top-level listening totals are not transmitted. The backend derives those from
canonical content/publication records. The backend is the only full
feedback-history store.

### 10.3 Follow and unfollow

All four follow events contain:

~~~json
{
  "action": "alexa",
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
  "action": "alexa",
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
  "action": "alexa",
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

An SQS message invokes `main.notification_handler`. The worker fetches the
notification with `POST /alexa/notification`, obtains a client-credentials token using scope
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
Lambda reports only the failed SQS `messageId`; after five receives the message
is sent to `ProactiveNotificationDeadLetterQueue`. Other rejection statuses are
posted as terminal delivery failures. Missing or already-completed
notifications are acknowledged without another send.

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
- Accept event envelope V3 and deduplicate on `eventId`.
- Persist raw event receipts before updating projections.
- Project playback, feedback, follow, and report events into backend-owned tables.
- Project notification preference events before publishing a notification message.
- Keep accepting the legacy V2 event envelope only for the agreed deployment window.
- Return `2xx` for duplicate event IDs and retryable `5xx` only for genuine ingestion failures.

### P1: deployment

- Deploy `HearListenerStateTable` as the sole listener-state table and grant the skill access only to it.
- Deploy the skill with `HEAR_DDB_TABLE` set to `HearListenerStateTable`.
- Deploy `ProactiveNotificationQueue` and configure its producer with the queue URL.
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
- A repeated SQS `eventId` does not produce a second proactive event.
- A creator update searches by `creatorId`; an organization update searches by
  `organizationId`, both bounded by `lastDate`.
- Notification items become `consumed` only after `AudioPlayer.PlaybackStarted`, and temporary playback failure returns them to `pending`.
- Disabling notifications stops future delivery without requiring account linking.

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
- `src/models/notifications.py`
- `src/services/notification_delivery.py`
- `src/clients/proactive.py`
- `schemas/listener-identity-resolve.schema.json`
- `schemas/listener-sync.schema.json`
- `schemas/resolver-request.schema.json`
- `schemas/search-request.schema.json`
- `schemas/backend-event.schema.json`
- `schemas/notification-item.schema.json`
- `schemas/notification-delivery-message.schema.json`
