# Hear Alexa Backend Event and Feedback Contract

Status: current implementation contract  
Source revision: `7808bdc`  
Audience: Hear backend, data, notification, moderation, and analytics services

This document describes every event currently emitted by the Hear Alexa skill, the direct listener-sync request, feedback eligibility, publication ownership, listening-time calculations, delivery guarantees, webhook verification, and recommended backend processing.

## 1. Contract summary

The skill emits these event families:

| Family | Event names |
|---|---|
| Playback | `playback.started`, `playback.progress`, `playback.nearly_finished`, `playback.stopped`, `playback.finished`, `playback.failed`, `playback.paused`, `playback.resumed`, `playback.cancelled` |
| Feedback | `feedback.given` |
| Following | `user.followed_creator`, `user.unfollowed_creator`, `user.followed_organization`, `user.unfollowed_organization` |
| Reporting | `user.reported_content`, `user.reported_creator` |

The skill also calls the listener-sync API directly:

```text
POST /alexa/listeners/sync
```

`playback.user_stopped` exists as a reserved constant but is not emitted by a current request path. The backend should not depend on receiving it.

## 2. Delivery architecture

The deployed flow is:

```text
Alexa skill Lambda
    -> Amazon SQS standard queue
    -> outbound consumer Lambda
    -> Hear backend webhook
```

The skill writes events to `SQS_OUT_QUEUE_URL`. The outbound consumer posts the exact event envelope to `WEBHOOK_OUTBOUND_URL`.

### 2.1 Canonical envelope

Every queued and webhook-delivered event uses this envelope:

```json
{
  "event": "playback.progress",
  "timestamp": "2026-08-31T11:41:22Z",
  "data": {}
}
```

| Field | Type | Meaning |
|---|---|---|
| `event` | string | Canonical event name from the catalog in this document. |
| `timestamp` | string | UTC envelope creation time in `YYYY-MM-DDTHH:MM:SSZ` format. |
| `data` | object | Event-specific payload. |

There is currently no explicit schema-version field. Consumers should ignore unknown fields and retain the raw envelope for forward compatibility.

### 2.2 SQS message attributes

The producer adds attributes when their source values are present:

| Attribute | Source |
|---|---|
| `eventType` | Envelope `event` |
| `subjectType` | `data.subjectType` |
| `subjectId` | `data.subjectId` |
| `publicationId` | `data.publicationId` |
| `notificationSubjectType` | `data.notificationSubjectType` |

These attributes can be used for queue filtering, but the JSON body is the canonical contract.

### 2.3 Webhook headers and signature

The outbound consumer sends:

```http
Content-Type: application/json
X-Api-Key: <HEAR_API_KEY>
x-webhook-timestamp: <unix-seconds>
x-webhook-signature: t=<unix-seconds>,v1=<lowercase-hex-hmac>
```

The signature input is the timestamp, a literal period, and the exact raw request body:

```text
signed_payload = x-webhook-timestamp + "." + raw_request_body
signature = HMAC-SHA256(WEBHOOK_OUTBOUND_SECRET, signed_payload)
```

If `WEBHOOK_OUTBOUND_SECRET` is empty, the client falls back to `HEAR_API_KEY` as the signing secret.

Backend verification should:

1. Read the raw body before JSON decoding.
2. Parse `t` and `v1` from `x-webhook-signature`.
3. Require `t` to equal `x-webhook-timestamp`.
4. Recalculate the hexadecimal HMAC over `t + "." + rawBody`.
5. Compare signatures using a constant-time comparison.
6. Reject stale timestamps according to backend policy; five minutes is a reasonable default.
7. Return a `2xx` response only after the event has been durably accepted or idempotently recognized.

Laravel-style verification example:

```php
$rawBody = $request->getContent();
$timestampHeader = $request->header('x-webhook-timestamp');
$signatureHeader = $request->header('x-webhook-signature');

preg_match('/^t=(\d+),v1=([a-f0-9]{64})$/', $signatureHeader, $matches);
$signedTimestamp = $matches[1] ?? '';
$received = $matches[2] ?? '';

abort_unless(hash_equals((string) $timestampHeader, (string) $signedTimestamp), 401);
abort_if(abs(time() - (int) $signedTimestamp) > 300, 401, 'Stale webhook');

$expected = hash_hmac(
    'sha256',
    $signedTimestamp . '.' . $rawBody,
    config('services.hear.webhook_secret'),
);

abort_unless(hash_equals($expected, $received), 401, 'Invalid webhook signature');
```

### 2.4 Retry and failure behavior

- SQS is a standard queue. Delivery is at least once and ordering is not guaranteed.
- The consumer processes batches of up to 10 messages.
- Any webhook exception or non-`2xx` response marks that SQS record as failed.
- Failed records are retried independently through partial batch failure reporting.
- After five receives, SQS moves the event to the dead-letter queue.
- The queue visibility timeout is 180 seconds.
- Queue and DLQ message retention are both 14 days.
- The webhook timeout is controlled by `HEAR_EVENT_WEBHOOK_TIMEOUT_MS`; deployment currently supplies 10 seconds.
- Malformed JSON in an SQS message is currently skipped and acknowledged rather than retried.
- If the original skill-to-SQS send fails, the Alexa interaction continues. There is no local retry after the event failed to enter SQS.

The backend must therefore be idempotent and must not assume event ordering.

## 3. Identity and ownership rules

### 3.1 Standalone content

For content that is not part of a publication:

```json
{
  "subjectType": "content",
  "subjectId": "content-uuid",
  "contentId": "content-uuid"
}
```

The content is the feedback, playback-history, analytics, and reporting unit.

### 3.2 Publication content

For a track belonging to a publication:

```json
{
  "subjectType": "publication",
  "subjectId": "publication-uuid",
  "publicationId": "publication-uuid",
  "trackContentId": "track-content-uuid"
}
```

The publication is the owning subject. The currently playing track is only a cursor within that publication.

Publication playback events do not include a top-level `contentId`. They use `trackContentId`. Publication feedback uses `contentIds` for the tracks represented by the feedback record.

Publication identity can be derived from the search filter's `publicationIds` even when individual API track objects do not contain `isPublication`, `type=publication`, or `publicationId`.

### 3.3 Session identifiers

| Field | Scope |
|---|---|
| `sessionId` | One playback session for one track. Replaying the same track can create another session. |
| `subjectSessionId` | The publication queue session for publication playback; otherwise equal to `sessionId`. |
| `queueId` | Queue instance used to navigate related content. May be `null`. |

For publication tracks in one queue, each track receives its own `sessionId`, while all tracks share the same `subjectSessionId`.

## 4. Playback events

### 4.1 Active playback event catalog

| Event | Trigger | Backend interpretation |
|---|---|---|
| `playback.started` | Alexa sends `AudioPlayer.PlaybackStarted`. | The device accepted the stream and playback began. |
| `playback.progress` | Alexa sends a delay or interval progress report. | Authoritative progress observation for position and time-spent updates. |
| `playback.nearly_finished` | Alexa sends `AudioPlayer.PlaybackNearlyFinished`. | Current track is close to its end; the skill may enqueue the next track. Do not treat it as completion. |
| `playback.stopped` | Alexa sends `AudioPlayer.PlaybackStopped`. | Device playback stopped at the supplied position. The local playback state becomes paused. |
| `playback.finished` | Alexa sends `AudioPlayer.PlaybackFinished`. | Track completed. Completion and feedback-candidate processing happen before this event is emitted. |
| `playback.failed` | Alexa sends `AudioPlayer.PlaybackFailed`. | Device failed to play the stream. |
| `playback.paused` | User pause/stop command, session flush, launch cleanup, or error cleanup. | Logical pause request/state flush. A later `playback.stopped` may also arrive from Alexa. |
| `playback.resumed` | Resume, repeat, start-over, seek, or playback-speed restart. | A new play directive is about to resume/restart the active track. A later `playback.started` confirms device playback. |
| `playback.cancelled` | User invokes `AMAZON.CancelIntent`. | The skill interaction and audio are explicitly cancelled. |

### 4.2 Common playback payload

All playback event data objects use these fields:

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `alexaUserId` | string | yes | Stable Alexa user identifier. Treat as sensitive pseudonymous data. |
| `listenerId` | string | no | Backend listener ID returned by listener sync. Omitted until available. |
| `subjectType` | `content` or `publication` | yes | Owning analytics and feedback subject. |
| `subjectId` | string | yes | Content ID for standalone content or publication ID for publication playback. |
| `creatorId` | string or null | yes, nullable | Creator known for the active content. |
| `queueId` | string or null | yes, nullable | Playback queue identifier. |
| `sessionId` | string | yes | Track playback-session identifier. |
| `subjectSessionId` | string | yes | Publication-level session or the standalone `sessionId`. |
| `eventType` | string | yes | Lowercase suffix matching the envelope name. |
| `positionMs` | integer | yes | Current track cursor in milliseconds. |
| `durationMs` | integer | yes | Known track duration, or `0`. |
| `listenedMs` | integer | yes | Furthest position reached during this track session. This is a high-water mark, not elapsed time. |
| `timeSpentMs` | integer | yes | Cumulative measured listening time for this track session. |
| `timeSpentHours` | number | yes | `timeSpentMs / 3,600,000`, rounded to six decimal places. |
| `completionPercentage` | integer or null | yes, nullable | `round(listenedMs / durationMs * 100)`, capped at 100. |
| `timestampMs` | integer | yes | Event creation time in Unix milliseconds. |
| `clientEventId` | string | yes | Playback event idempotency key. |

Playback `clientEventId` format:

```text
<subjectSessionId-or-sessionId>:<eventType>:<timestampMs>
```

### 4.3 Standalone playback fields

Standalone playback adds:

| Field | Type | Meaning |
|---|---|---|
| `contentId` | string | Playing content ID; equal to `subjectId`. |

Example:

```json
{
  "event": "playback.progress",
  "timestamp": "2026-08-31T11:41:22Z",
  "data": {
    "alexaUserId": "amzn1.ask.account.example",
    "listenerId": "listener-uuid",
    "subjectType": "content",
    "subjectId": "content-uuid",
    "contentId": "content-uuid",
    "creatorId": "creator-uuid",
    "queueId": "queue-uuid",
    "sessionId": "content-uuid:track-session-token",
    "subjectSessionId": "content-uuid:track-session-token",
    "eventType": "progress",
    "positionMs": 120000,
    "durationMs": 180000,
    "listenedMs": 120000,
    "timeSpentMs": 115000,
    "timeSpentHours": 0.031944,
    "completionPercentage": 67,
    "timestampMs": 1788176482000,
    "clientEventId": "content-uuid:track-session-token:progress:1788176482000"
  }
}
```

### 4.4 Publication playback fields

Publication playback adds:

| Field | Type | Meaning |
|---|---|---|
| `publicationId` | string | Publication owning the tracks; equal to `subjectId`. |
| `trackContentId` | string | Currently playing track. |
| `trackIndex` | integer or null | Zero-based track index when known. |
| `trackCount` | integer or null | Total publication track count when known. |
| `publicationTimeSpentMs` | integer | Aggregate listening time accumulated for the current publication feedback period. |
| `publicationTimeSpentHours` | number | Publication aggregate converted to hours. |
| `trackListening` | array | Current per-track aggregate snapshot. |

Each `trackListening` entry is:

| Field | Type | Meaning |
|---|---|---|
| `contentId` | string | Track content ID. |
| `trackIndex` | integer or null | Zero-based position in the publication. |
| `durationMs` | integer | Known track duration or `0`. |
| `listenedMs` | integer | Track position high-water mark. |
| `timeSpentMs` | integer | Accumulated listening time for this track across captured sessions. |
| `timeSpentHours` | number | Track aggregate converted to hours. |
| `completed` | boolean | Whether the track completed. |

Example:

```json
{
  "event": "playback.stopped",
  "timestamp": "2026-08-31T11:41:22Z",
  "data": {
    "alexaUserId": "amzn1.ask.account.example",
    "listenerId": "listener-uuid",
    "subjectType": "publication",
    "subjectId": "publication-uuid",
    "publicationId": "publication-uuid",
    "trackContentId": "track-2-uuid",
    "creatorId": "creator-uuid",
    "queueId": "queue-uuid",
    "sessionId": "track-2-uuid:track-session-token",
    "subjectSessionId": "publication:publication-uuid:queue-uuid",
    "eventType": "stopped",
    "trackIndex": 1,
    "trackCount": 3,
    "positionMs": 120000,
    "durationMs": 180000,
    "listenedMs": 120000,
    "timeSpentMs": 900000,
    "timeSpentHours": 0.25,
    "completionPercentage": 67,
    "publicationTimeSpentMs": 1800000,
    "publicationTimeSpentHours": 0.5,
    "trackListening": [
      {
        "contentId": "track-1-uuid",
        "trackIndex": 0,
        "durationMs": 900000,
        "listenedMs": 900000,
        "timeSpentMs": 900000,
        "timeSpentHours": 0.25,
        "completed": true
      },
      {
        "contentId": "track-2-uuid",
        "trackIndex": 1,
        "durationMs": 180000,
        "listenedMs": 120000,
        "timeSpentMs": 900000,
        "timeSpentHours": 0.25,
        "completed": false
      }
    ],
    "timestampMs": 1788176482000,
    "clientEventId": "publication:publication-uuid:queue-uuid:stopped:1788176482000"
  }
}
```

### 4.5 Listening-time semantics

The backend must distinguish three measurements:

| Measurement | Semantics | Additive? |
|---|---|---:|
| `positionMs` | Current cursor. Can move backward or forward. | no |
| `listenedMs` | Furthest cursor reached. Used for completion and feedback coverage. | no |
| `timeSpentMs` | Cumulative elapsed listening time for the session or aggregate represented by the object. | no; compute deltas or upsert maxima |

The skill calculates track-session time from Alexa event timestamps while the prior state is `starting` or `playing` and the playback offset advanced. A forward seek adds only elapsed wall-clock time rather than the skipped offset. A backward offset does not add time for that observation. Duplicate Alexa request IDs and older Alexa timestamps are rejected before state update.

The skill retains the latest 20 diagnostic sessions per track but preserves the accumulated track total when older session details are removed. Publication hours are:

```text
publicationTimeSpentMs = sum(track.timeSpentMs)
publicationTimeSpentHours = round(publicationTimeSpentMs / 3_600_000, 6)
```

Do not sum the cumulative `timeSpentMs` from every progress event. Recommended processing is:

```text
previous = stored timeSpentMs for sessionId, default 0
incoming = event.data.timeSpentMs
delta = max(0, incoming - previous)

upsert session timeSpentMs = max(previous, incoming)
increment subject aggregate by delta
```

Similarly, `trackListening` is a snapshot. Upsert its per-track values; do not add the complete snapshot on every event.

For `playback.finished`, `listenedMs` is forced to at least the known track duration so completion is unambiguous. `timeSpentMs` is not forced to the duration.

## 5. Feedback lifecycle and event

### 5.1 Feedback values

`feedback.given.data.feedback` is one of:

| Value | Alexa intent or path |
|---|---|
| `enjoyed` | `FeedbackEnjoyedIntent` or contextual yes |
| `somewhat` | `FeedbackSomewhatIntent` |
| `not_enjoyed` | `FeedbackNotEnjoyedIntent` or contextual no |
| `skipped` | `SkipFeedbackIntent` |

Skipping is still a recorded feedback event; it is not silently discarded.

### 5.2 Standalone feedback eligibility

Standalone content creates a feedback candidate after `PlaybackFinished`. The feedback subject is that content ID.

### 5.3 Publication feedback eligibility

Publication feedback is created for the publication as a whole, never for an individual publication track.

A track is meaningful when either:

- it completed; or
- its `listenedMs` reached at least 50% of its known duration; or
- duration is unknown and `listenedMs` reached 60,000 ms.

Publication coverage is calculated as follows:

- If total publication duration is known: sum each track's capped listened time and divide by total duration.
- Otherwise: divide meaningful track count by expected track count.
- Coverage is capped at `1.0`.

A publication becomes feedback-eligible when:

```text
coverage >= 0.5
AND
(expectedTrackCount == 1 OR meaningfulTrackCount >= 2)
```

The skill finalizes a publication when it reaches its final track or playback moves to a different publication. A publication feedback key is:

```text
publication:<publicationId>
```

Answered feedback keys are retained locally to prevent the skill repeatedly asking for the same subject.

### 5.4 Feedback payload fields

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `alexaUserId` | string | yes | Alexa user identifier. |
| `listenerId` | string | no | Synced backend listener ID. |
| `feedbackKey` | string | normally | Stable skill-side feedback subject key. |
| `subjectType` | `content` or `publication` | yes | Feedback owner. |
| `subjectId` | string | yes | Content ID or publication ID. |
| `title` | string | no | Spoken subject title. |
| `publicationTitle` | string | no | Publication title. |
| `creatorId` | string | no | Associated creator. |
| `creatorName` | string | no | Associated creator name. |
| `organizationId` | string | no | Associated publisher/organization. |
| `organizationName` | string | no | Associated organization name. |
| `category` | string or object | no | Category as available in playback state. |
| `listenedMs` | integer | no | Content high-water position, or sum of publication track high-water values. |
| `timeSpentMs` | integer | no | Content session time or publication aggregate time. |
| `timeSpentHours` | number | no | Time converted to hours. |
| `trackListening` | array | publication only | Per-track publication listening snapshot. |
| `feedback` | string | yes | One of the four values above. |
| `coverage` | number | publication normally | Publication coverage from `0.0` to `1.0`. |
| `expectedTrackCount` | integer | publication normally | Expected publication track count. |
| `meaningfulTrackCount` | integer | publication normally | Tracks that met the meaningful threshold. |
| `timestamp` | integer | yes | Feedback recording time in Unix milliseconds. |
| `clientEventId` | string | yes | Feedback idempotency key. |

Feedback `clientEventId` format:

```text
feedback:<alexaUserId>:<feedbackKey-or-subjectId>:<feedback-value>
```

#### Standalone feedback identity fields

| Field | Type | Meaning |
|---|---|---|
| `contentId` | string | Content receiving the feedback. |
| `parentPublicationId` | string | Present only if a content feedback record has publication context. Current publication flow normally emits publication feedback instead. |

Standalone example:

```json
{
  "event": "feedback.given",
  "timestamp": "2026-08-31T12:15:00Z",
  "data": {
    "alexaUserId": "amzn1.ask.account.example",
    "listenerId": "listener-uuid",
    "feedbackKey": "content-uuid",
    "subjectType": "content",
    "subjectId": "content-uuid",
    "contentId": "content-uuid",
    "title": "Local sports update",
    "creatorId": "creator-uuid",
    "organizationId": "organization-uuid",
    "listenedMs": 180000,
    "timeSpentMs": 172000,
    "timeSpentHours": 0.047778,
    "feedback": "enjoyed",
    "timestamp": 1788178500000,
    "clientEventId": "feedback:amzn1.ask.account.example:content-uuid:enjoyed"
  }
}
```

#### Publication feedback identity fields

| Field | Type | Meaning |
|---|---|---|
| `publicationId` | string | Publication receiving feedback; equal to `subjectId`. |
| `contentIds` | string array | Track IDs represented by the finalized publication feedback. |

Publication example:

```json
{
  "event": "feedback.given",
  "timestamp": "2026-08-31T12:15:00Z",
  "data": {
    "alexaUserId": "amzn1.ask.account.example",
    "listenerId": "listener-uuid",
    "feedbackKey": "publication:publication-uuid",
    "subjectType": "publication",
    "subjectId": "publication-uuid",
    "publicationId": "publication-uuid",
    "contentIds": ["track-1-uuid", "track-2-uuid"],
    "title": "Weekly edition",
    "publicationTitle": "Weekly edition",
    "organizationId": "organization-uuid",
    "organizationName": "York Talking News",
    "coverage": 1.0,
    "expectedTrackCount": 2,
    "meaningfulTrackCount": 2,
    "listenedMs": 1800000,
    "timeSpentMs": 1800000,
    "timeSpentHours": 0.5,
    "trackListening": [
      {
        "contentId": "track-1-uuid",
        "trackIndex": 0,
        "durationMs": 900000,
        "listenedMs": 900000,
        "timeSpentMs": 900000,
        "timeSpentHours": 0.25,
        "completed": true
      },
      {
        "contentId": "track-2-uuid",
        "trackIndex": 1,
        "durationMs": 900000,
        "listenedMs": 900000,
        "timeSpentMs": 900000,
        "timeSpentHours": 0.25,
        "completed": true
      }
    ],
    "feedback": "enjoyed",
    "timestamp": 1788178500000,
    "clientEventId": "feedback:amzn1.ask.account.example:publication:publication-uuid:enjoyed"
  }
}
```

The publication example's `clientEventId` contains two adjacent `publication` segments because the `feedbackKey` itself starts with `publication:`. This is expected.

### 5.5 Recommended feedback persistence

The backend should enforce a unique constraint on `clientEventId` and store:

- the raw envelope;
- resolved listener ID and Alexa user ID;
- subject type and subject ID;
- the feedback value;
- playback coverage and time snapshot;
- publication track IDs and track-listening snapshot when present;
- received-at and skill-recorded timestamps.

Upsert publication feedback against the publication, not against the latest track. Track rows are supporting evidence and analytics detail.

## 6. Follow and unfollow events

### 6.1 Event names

| Event | Meaning |
|---|---|
| `user.followed_creator` | Listener followed a creator. |
| `user.unfollowed_creator` | Listener unfollowed a creator. |
| `user.followed_organization` | Listener followed a publisher/organization. |
| `user.unfollowed_organization` | Listener unfollowed a publisher/organization. |

### 6.2 Payload

```json
{
  "event": "user.followed_organization",
  "timestamp": "2026-08-31T12:20:00Z",
  "data": {
    "alexaUserId": "amzn1.ask.account.example",
    "userId": "amzn1.ask.account.example",
    "listenerId": "listener-uuid",
    "sourceType": "organization",
    "sourceId": "organization-uuid",
    "sourceName": "York Talking News",
    "notificationSubjectType": "publication",
    "timestamp": 1788178800000
  }
}
```

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `alexaUserId` | string | yes | Alexa user identifier. |
| `userId` | string | yes | Compatibility alias equal to `alexaUserId`. |
| `listenerId` | string | no | Synced backend listener ID. |
| `sourceType` | `creator` or `organization` | yes | Type being followed. |
| `sourceId` | string | yes | Creator or organization ID. |
| `sourceName` | string | no | Display name. |
| `notificationSubjectType` | `publication` | yes | New-content notification unit. Currently always publication. |
| `timestamp` | integer | yes | Action time in Unix milliseconds. |

These events do not currently include `clientEventId`. Recommended backend deduplication key:

```text
<event>:<alexaUserId>:<sourceType>:<sourceId>:<timestamp>
```

The backend should use the event name and `sourceType` to add or remove the follow. `notificationSubjectType=publication` means notifications generated from this relationship should refer to newly published publications rather than arbitrary individual tracks.

No separate `publication.published` notification event originates from the Alexa skill. Publication publishing and notification fan-out are backend responsibilities.

## 7. Report events

### 7.1 Event names

| Event | Meaning |
|---|---|
| `user.reported_content` | Listener reported the current track/content. |
| `user.reported_creator` | Listener reported the current creator. |

### 7.2 Payload

```json
{
  "event": "user.reported_content",
  "timestamp": "2026-08-31T12:25:00Z",
  "data": {
    "subjectType": "content",
    "subjectId": "track-uuid",
    "subjectName": "Track title",
    "contentId": "track-uuid",
    "publicationId": "publication-uuid",
    "recordedAt": 1788179100000,
    "status": "pending",
    "alexaUserId": "amzn1.ask.account.example",
    "userId": "amzn1.ask.account.example",
    "listenerId": "listener-uuid",
    "reason": "reported_via_alexa",
    "clientEventId": "alexa-report:amzn1.ask.account.example:content:track-uuid"
  }
}
```

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `subjectType` | `content` or `creator` | yes | Moderation subject. |
| `subjectId` | string | yes | Reported content or creator ID. |
| `subjectName` | string | no | Known display name/title. |
| `contentId` | string | no | Playing content context. |
| `publicationId` | string | no | Parent publication context. Reporting a publication track still reports the content track. |
| `recordedAt` | integer | yes | Action time in Unix milliseconds. |
| `status` | `pending` | yes | Initial moderation status. |
| `alexaUserId` | string | yes | Alexa user identifier. |
| `userId` | string | yes | Compatibility alias equal to `alexaUserId`. |
| `listenerId` | string | no | Synced backend listener ID. |
| `reason` | `reported_via_alexa` | yes | Fixed source/reason marker. |
| `clientEventId` | string | yes | Report idempotency key. |

Report `clientEventId` format:

```text
alexa-report:<alexaUserId>:<subjectType>:<subjectId>
```

The backend should upsert by `clientEventId`, create or update a moderation case, and preserve `contentId`/`publicationId` as context rather than changing the report's owning subject.

## 8. Listener sync

Listener sync is not an SQS event. On launch, when enabled, the skill directly calls:

```http
POST <HEAR_API_URL>/alexa/listeners/sync
X-Api-Key: <HEAR_API_KEY>
Content-Type: application/json
```

The request times out after 2.5 seconds in the launch flow. Failure is non-blocking.

### 8.1 Required request fields

| Field | Type | Meaning |
|---|---|---|
| `alexaUserId` | string | Stable Alexa listener identity. |
| `listenerType` | `guest` or `registered` | Registration state derived from authorized profile data. |
| `clientVersion` | `hear-alexa-python` | Current hardcoded client identifier. |

### 8.2 Common optional request fields

| Field | Type | Meaning |
|---|---|---|
| `deviceId` | string or null | Alexa device ID. |
| `apiEndpoint` | string or null | Alexa regional API endpoint. |
| `locale` | string or null | Request locale such as `en-GB`. |
| `listeningPattern` | object or null | Persisted listening preferences/pattern. |
| `followedCreatorIds` | string array | Followed creators. |
| `followedOrganizationIds` | string array | Followed organizations. |
| `playbackSpeed` | number or null | Listener playback-speed preference. |
| `playCount` | integer | Number of skill-side playback starts. |
| `lastPlayedAt` | integer or null | Last playback time when present. |
| `recentPlayedIds` | string array | Deduplicated recent subject IDs. Publications use publication IDs. |
| `recentPlays` | object array | Up to 20 normalized recent-play records. |

### 8.3 Registered-only fields

These fields are sent only when the skill holds both an authorized email and an authorized name:

| Field | Type |
|---|---|
| `userName` | string or null |
| `userEmail` | string |
| `address` | string or null |
| `city` | string or null |
| `state` | string or null |
| `country` | string or null |
| `countryCode` | string or null |
| `postalCode` | string or null |
| `latitude` | number or null |
| `longitude` | number or null |
| `locality` | string or null |

Guests are still synced, but protected name, email, address, postcode, and coordinates are excluded. A listener can therefore use the skill and accumulate playback history without granting optional permissions.

### 8.4 Recent-play identity

A standalone recent play is owned by its content:

```json
{
  "subjectType": "content",
  "subjectId": "content-uuid",
  "contentId": "content-uuid",
  "timeSpentMs": 900000,
  "timeSpentHours": 0.25,
  "sessions": {}
}
```

A publication recent play is owned by the publication and retains its latest track cursor plus per-track totals:

```json
{
  "subjectType": "publication",
  "subjectId": "publication-uuid",
  "publicationId": "publication-uuid",
  "trackContentId": "track-2-uuid",
  "timeSpentMs": 2700000,
  "timeSpentHours": 0.75,
  "tracks": {
    "track-1-uuid": {
      "contentId": "track-1-uuid",
      "timeSpentMs": 1800000,
      "timeSpentHours": 0.5,
      "sessions": {}
    },
    "track-2-uuid": {
      "contentId": "track-2-uuid",
      "timeSpentMs": 900000,
      "timeSpentHours": 0.25,
      "sessions": {}
    }
  }
}
```

The backend should treat `recentPlays` as an upsert snapshot, not as additive event rows.

### 8.5 Expected response

A successful backend response must be HTTP `200` with a JSON object. The skill accepts either identifier field:

```json
{
  "listenerId": "listener-uuid"
}
```

or:

```json
{
  "id": "listener-uuid"
}
```

The returned identifier is persisted and included as `listenerId` in later events.

The machine-readable baseline schema is in `schemas/listener-sync.schema.json`; the running code additionally sends `followedOrganizationIds` and the enriched recent-play objects described here.

## 9. Backend ingestion recommendations

### 9.1 Idempotency

Use these primary keys where supplied:

| Family | Recommended unique key |
|---|---|
| Playback | `clientEventId` |
| Feedback | `clientEventId` |
| Report | `clientEventId` |
| Follow/unfollow | Composite event, user, source, and timestamp key |

Do not use only `subjectId`; one subject legitimately generates many playback events.

### 9.2 Ordering

Do not assume SQS order. Use `timestampMs` for playback ordering and the payload `timestamp`/`recordedAt` for action ordering. Ignore an older state transition when a newer stored event for the same `sessionId` already supersedes it, but retain the raw event for audit if desired.

### 9.3 Cumulative metrics

These are cumulative snapshots and must not be summed repeatedly:

- playback `listenedMs`;
- playback `timeSpentMs`;
- publication `publicationTimeSpentMs`;
- every entry in `trackListening`;
- listener-sync `recentPlays` metrics.

Maintain the last value per session or subject and add only a non-negative delta.

### 9.4 Subject routing

```text
if subjectType == "publication":
    own feedback/history/aggregate by publicationId
    use trackContentId or contentIds only for detail
else:
    own feedback/history/aggregate by contentId
```

For reports, use the report's `subjectType`/`subjectId`; `publicationId` is context only.

### 9.5 Null and omitted fields

- Playback payloads can contain explicit `null` values for optional fields.
- Feedback, follow, and report payload builders generally omit fields whose value is `null`.
- Empty arrays can still be present.
- IDs should be treated as opaque strings.
- Consumers should ignore unknown fields.

### 9.6 Suggested storage model

A practical backend model is:

```text
alexa_event_receipts
    client_event_id / generated dedupe key
    event_name
    alexa_user_id
    listener_id
    subject_type
    subject_id
    event_timestamp
    raw_envelope

playback_sessions
    session_id
    subject_session_id
    subject_type
    subject_id
    publication_id
    track_content_id / content_id
    position_ms
    listened_ms
    time_spent_ms
    status / latest_event_type
    last_event_timestamp_ms

publication_track_listening
    publication_id
    content_id
    listener_id or alexa_user_id
    listened_ms
    time_spent_ms
    completed

feedback
    client_event_id
    feedback_key
    subject_type
    subject_id
    value
    coverage
    time_spent_ms
    raw_track_listening

follows
    listener identity
    source_type
    source_id
    notification_subject_type
    followed_at / unfollowed_at

moderation_reports
    client_event_id
    subject_type
    subject_id
    content_id
    publication_id
    status
    reason
```

## 10. Backend acceptance checklist

- [ ] Webhook route accepts the canonical envelope.
- [ ] Signature verification uses the exact raw body and Unix-second timestamp.
- [ ] Endpoint returns `2xx` only after durable acceptance.
- [ ] Playback, feedback, and report handlers enforce `clientEventId` uniqueness.
- [ ] Follow/unfollow handler has a composite deduplication strategy.
- [ ] Publication playback routes by `publicationId`, not `trackContentId`.
- [ ] Publication feedback updates the publication as a whole.
- [ ] `trackListening` is stored as a snapshot/upsert.
- [ ] Cumulative times are delta-processed rather than repeatedly summed.
- [ ] Guest events work without `listenerId`.
- [ ] Listener sync accepts guest payloads without protected profile/location fields.
- [ ] Listener sync returns `listenerId` or `id` in an HTTP `200` JSON response.
- [ ] Unknown fields are ignored and raw envelopes are retained.
- [ ] Queue age and dead-letter queue alarms are monitored.

## 11. Source-of-truth files

The implementation behind this contract is located in:

- `src/constants/events.py`
- `src/services/events.py`
- `src/clients/events.py`
- `src/utils/events.py`
- `src/utils/playback.py`
- `src/utils/playback_history.py`
- `src/models/playback.py`
- `src/models/playback_state.py`
- `src/models/feedback.py`
- `src/models/report.py`
- `src/models/social.py`
- `src/services/listener_sync.py`
- `schemas/listener-sync.schema.json`
- `template.yaml`
