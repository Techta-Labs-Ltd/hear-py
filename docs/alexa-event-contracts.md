# Alexa Outbound Event Contracts

## Scope

This document covers every outbound Alexa data contract: listener registration
through the listener-sync endpoint, then version 3 playback, feedback, follow,
report, and notification-preference events sent through SQS. Notification
delivery in the opposite direction is outside this document.

## Delivery

```text
Alexa request or AudioPlayer callback
    -> Alexa Lambda creates one event
    -> SQS
    -> outbound worker Lambda
    -> Hear backend webhook
```

The request path only waits for SQS, not the backend. Delivery is at least once.
The backend must deduplicate by `eventId`. Failed SQS records are retried; records
that exhaust the retry policy move to the dead-letter queue.

The worker sends the exact SQS body to the configured webhook. Authentication is
the API key plus an HMAC signature of `<unix-seconds>.<exact-request-body>`.

## The ID rule

| Field | Exact meaning | When present |
| --- | --- | --- |
| `listenerId` | The Hear listener receiving or producing the event | Whenever canonical identity is available |
| `contentId` | The actual playable track involved in this event | Every playback event and content feedback |
| `publicationId` | The publication that contains the track, or the publication being rated | Publication playback and publication feedback only |

For a track played from a publication, send both IDs:

```json
{
  "contentId": "track-2",
  "publicationId": "publication-1"
}
```

Never use `publicationId` as the track ID. Never use `contentId` as the
publication ID. Version 3 does not send the redundant `subjectId` or
`trackContentId` fields.

## Common envelope

```json
{
  "event": "playback.finished",
  "schemaVersion": 3,
  "eventId": "session-1:finished:1789128000000",
  "timestamp": "2026-09-11T12:00:00Z",
  "data": {
    "action": "alexa",
    "alexaUserId": "amzn1.ask.account.example",
    "listenerId": "listener-7",
    "clientEventId": "session-1:finished:1789128000000"
  }
}
```

Rules:

- `schemaVersion` is `3`.
- `data.action` is always `alexa` and is set by the envelope builder.
- `eventId` equals `data.clientEventId` for normal domain events.
- Missing optional fields are omitted rather than sent as `null`.
- `timestamp` is UTC ISO 8601; event measurements use Unix milliseconds.

## Actual outbound SQS event catalogue

These are all event names currently produced by the Alexa code:

| Trigger | Event name |
| --- | --- |
| Audio starts | `playback.started` |
| Playback progress callback | `playback.progress` |
| Audio is nearly finished | `playback.nearly_finished` |
| Listener pauses or an active session is safely flushed | `playback.paused` |
| Listener resumes | `playback.resumed` |
| Alexa stops playback | `playback.stopped` |
| Audio finishes | `playback.finished` |
| Audio playback fails | `playback.failed` |
| Listener answers the feedback question | `feedback.given` |
| Listener follows a creator | `user.followed_creator` |
| Listener unfollows a creator | `user.unfollowed_creator` |
| Listener follows an organization | `user.followed_organization` |
| Listener unfollows an organization | `user.unfollowed_organization` |
| Listener reports content | `user.reported_content` |
| Listener reports a creator | `user.reported_creator` |
| Listener enables Hear notifications | `notifications.enabled` |
| Listener disables Hear notifications | `notifications.disabled` |

Listener registration and notification fetch/update/delivery status are HTTP
contracts, not domain events in this SQS catalogue.

## Listener registration (HTTP)

Registration is not an SQS event. Alexa sends it directly to the listener-sync
endpoint after launch or a profile-permission update:

```http
POST <HEAR_API_URL>/<HEAR_API_PATH_PREFIX>/listeners/sync
X-Api-Key: <HEAR_API_KEY>
Content-Type: application/json
```

The request contains only the identity and permitted profile values:

```json
{
  "action": "alexa",
  "alexaUserId": "amzn1.ask.account.example",
  "listenerId": "listener-7",
  "listenerName": "Alex Morgan",
  "email": "listener@example.com",
  "city": "Manchester",
  "longitude": -2.2426,
  "latitude": 53.4808
}
```

`listenerName` is the listener's display name; it must not be replaced with a
creator or organization name. `listenerId` may be `null` on the first sync and
is filled from the response for later calls. Name, email, and location are sent
only after the Alexa permissions needed to obtain them have been granted.
Latitude is `-90..90` and longitude is `-180..180`. No device ID, skill ID,
environment, locale, playback setting, address, country, or client-version
metadata is sent.

Machine-readable request schema:
[`schemas/listener-sync.schema.json`](../schemas/listener-sync.schema.json).

## Playback

Supported envelope names are `playback.started`, `playback.progress`,
`playback.nearly_finished`, `playback.paused`, `playback.resumed`,
`playback.stopped`, `playback.finished`, and `playback.failed`. The suffix must
equal `data.eventType`.

### Standalone content

```json
{
  "event": "playback.finished",
  "schemaVersion": 3,
  "eventId": "track-session-1:finished:1789128000000",
  "timestamp": "2026-09-11T12:00:00Z",
  "data": {
    "action": "alexa",
    "alexaUserId": "amzn1.ask.account.example",
    "listenerId": "listener-7",
    "subjectType": "content",
    "contentId": "track-1",
    "sessionId": "track-session-1",
    "subjectSessionId": "track-session-1",
    "eventType": "finished",
    "positionMs": 180000,
    "durationMs": 180000,
    "listenedMs": 180000,
    "timeSpentMs": 176000,
    "timestampMs": 1789128000000,
    "clientEventId": "track-session-1:finished:1789128000000"
  }
}
```

### Content inside a publication

```json
{
  "event": "playback.stopped",
  "schemaVersion": 3,
  "eventId": "publication:publication-1:session-1:stopped:1789128000000",
  "timestamp": "2026-09-11T12:00:00Z",
  "data": {
    "action": "alexa",
    "alexaUserId": "amzn1.ask.account.example",
    "listenerId": "listener-7",
    "subjectType": "publication",
    "contentId": "track-2",
    "publicationId": "publication-1",
    "trackIndex": 1,
    "trackCount": 3,
    "sessionId": "track-session-2",
    "subjectSessionId": "publication:publication-1:session-1",
    "eventType": "stopped",
    "positionMs": 120000,
    "durationMs": 180000,
    "listenedMs": 120000,
    "timeSpentMs": 115000,
    "timestampMs": 1789128000000,
    "clientEventId": "publication:publication-1:session-1:stopped:1789128000000"
  }
}
```

Playback field meanings:

| Field | Meaning |
| --- | --- |
| `sessionId` | One playback attempt for the current content |
| `subjectSessionId` | Groups the lifecycle of the standalone content or publication session |
| `positionMs` | Current playback cursor |
| `durationMs` | Current content duration |
| `listenedMs` | Furthest valid position heard |
| `timeSpentMs` | Measured listening time, excluding seek distance |
| `trackIndex` | Zero-based position within the publication |
| `trackCount` | Known number of tracks in the publication |

Hours and completion percentages are derived values and are not transmitted.
Publication totals and the full `trackListening` array are not repeated on every
playback callback.

## Feedback

Allowed values are `enjoyed`, `somewhat`, `not_enjoyed`, and `skipped`.

### Content feedback

```json
{
  "event": "feedback.given",
  "schemaVersion": 3,
  "eventId": "feedback:listener-7:track-1:enjoyed",
  "timestamp": "2026-09-11T12:05:00Z",
  "data": {
    "action": "alexa",
    "alexaUserId": "amzn1.ask.account.example",
    "listenerId": "listener-7",
    "subjectType": "content",
    "contentId": "track-1",
    "feedback": "enjoyed",
    "timestampMs": 1789128300000,
    "clientEventId": "feedback:listener-7:track-1:enjoyed"
  }
}
```

### Publication feedback

```json
{
  "event": "feedback.given",
  "schemaVersion": 3,
  "eventId": "feedback:listener-7:publication:publication-1:somewhat",
  "timestamp": "2026-09-11T12:05:00Z",
  "data": {
    "action": "alexa",
    "alexaUserId": "amzn1.ask.account.example",
    "listenerId": "listener-7",
    "subjectType": "publication",
    "publicationId": "publication-1",
    "trackListening": [
      {
        "contentId": "track-1",
        "trackIndex": 0,
        "durationMs": 900000,
        "listenedMs": 900000,
        "timeSpentMs": 890000,
        "completed": true
      },
      {
        "contentId": "track-2",
        "trackIndex": 1,
        "durationMs": 180000,
        "listenedMs": 120000,
        "timeSpentMs": 115000,
        "completed": false
      }
    ],
    "feedback": "somewhat",
    "timestampMs": 1789128300000,
    "clientEventId": "feedback:listener-7:publication:publication-1:somewhat"
  }
}
```

The publication-level feedback owns `publicationId`. Each array entry owns its
own `contentId`. The backend can derive titles, creator and organization data,
category, coverage, hours, percentages, and the publication's ordered content
IDs from canonical records, so Alexa does not duplicate them in the payload.

The following former fields are deliberately not sent in feedback:
`feedbackKey`, `subjectId`, `contentIds`, `title`, `publicationTitle`,
`creatorId`, `creatorName`, `organizationId`, `organizationName`, `category`,
`coverage`, `expectedTrackCount`, `meaningfulTrackCount`, `timeSpentHours`, and
top-level publication listening totals.

## Follow and unfollow

Events are `user.followed_creator`, `user.unfollowed_creator`,
`user.followed_organization`, and `user.unfollowed_organization`.

```json
{
  "action": "alexa",
  "alexaUserId": "amzn1.ask.account.example",
  "listenerId": "listener-7",
  "sourceType": "organization",
  "sourceId": "organization-42",
  "sourceName": "Pendle Voice",
  "notificationSubjectType": "publication",
  "timestamp": 1789128600000,
  "clientEventId": "follow:listener-7:follow:organization:organization-42"
}
```

The JSON above is the envelope's `data`. Follow state is keyed by
`listenerId + sourceType + sourceId`.

## Reports

Events are `user.reported_content` and `user.reported_creator`. Reports retain
`subjectId` because their subject can be either content or a creator; this does
not change the playback/feedback ID rule. A content report may also contain
`contentId` and `publicationId` as captured report context.

## Notification preferences

Events are `notifications.enabled` and `notifications.disabled`. Data contains
`action`, `alexaUserId`, `listenerId`, `enabled`, `permissionGranted`,
`timestamp`, and `clientEventId`.

## SQS routing attributes

The body is always the complete envelope. When values exist, SQS attributes are
`eventType`, `eventId`, `schemaVersion`, `action`, `listenerId`, `subjectType`,
`contentId`, `publicationId`, `sourceType`, `sourceId`, and
`notificationSubjectType`.

## Acceptance rules

- Every emitted envelope is version 3 and contains `data.action=alexa`.
- Every playback event contains the current `contentId`.
- Publication playback also contains `publicationId`.
- Content feedback contains `contentId` and no `publicationId`.
- Publication feedback contains `publicationId`; per-track data uses
  `trackListening[].contentId`.
- Negative time values are rejected or normalized before delivery.
- No token, audio URL, email, coordinates, API key, or complete personal payload
  is logged.
- Backend processing is idempotent on `eventId`.

Machine-readable envelope schema:
[`schemas/backend-event.schema.json`](../schemas/backend-event.schema.json).
