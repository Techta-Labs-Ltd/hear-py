# Backend creator notification integration

This document defines the contract the Hear backend must implement to notify
Alexa listeners when a creator they follow publishes a new track or
publication.

## End-to-end flow

```text
Listener follows a creator in Alexa
  -> Alexa sends user.followed_creator to the Hear backend
  -> Alexa sends notification.subscribed with the listener's creator IDs
  -> Hear backend stores the Alexa user/creator subscription
  -> Creator publishes a track or publication
  -> Hear backend selects subscribed Alexa user IDs
  -> Hear backend posts one notification event to the Alexa webhook
  -> Alexa stores one inbox record per recipient for seven days
  -> Alexa offers the updates on the listener's next skill launch
     or when the listener asks to hear notifications
```

The current Alexa implementation provides an in-skill inbox. It does not call
the Alexa Proactive Events API, so posting a notification does not produce a
device light, mobile push, or unsolicited announcement while the skill is
closed.

## Alexa-to-backend events

Production sends these events asynchronously through SQS to:

```text
POST https://alexa.hear.media/api/v1/alexa/events
```

Every request uses the common envelope:

```json
{
  "event": "user.followed_creator",
  "timestamp": "2026-08-02T12:00:00Z",
  "data": {}
}
```

The backend must authenticate `X-Api-Key`, verify the HMAC signature against
the exact raw request body, and make event processing idempotent. SQS delivery
is at least once, so duplicate events are possible.

### `user.followed_creator`

Sent when a listener follows a creator.

```json
{
  "event": "user.followed_creator",
  "timestamp": "2026-08-02T12:00:00Z",
  "data": {
    "userId": "amzn1.ask.account.EXAMPLE",
    "listenerId": "hear-listener-id",
    "creatorId": "creator-id",
    "creatorName": "Creator name",
    "timestamp": 1785672000000
  }
}
```

The backend should upsert the relationship identified by `userId` and
`creatorId`. Reprocessing the same relationship must not create duplicates.

### `user.unfollowed_creator`

Sent when a listener unfollows a creator.

```json
{
  "event": "user.unfollowed_creator",
  "timestamp": "2026-08-02T12:05:00Z",
  "data": {
    "userId": "amzn1.ask.account.EXAMPLE",
    "listenerId": "hear-listener-id",
    "creatorId": "creator-id",
    "timestamp": 1785672300000
  }
}
```

The backend must deactivate or remove this user's creator subscription. The
operation must remain successful if the relationship is already absent.

### `notification.subscribed`

Sent after the listener grants notification permission and whenever Alexa
refreshes the subscription after following another creator.

```json
{
  "event": "notification.subscribed",
  "timestamp": "2026-08-02T12:10:00Z",
  "data": {
    "userId": "amzn1.ask.account.EXAMPLE",
    "listenerId": "hear-listener-id",
    "deviceId": "alexa-device-id",
    "categories": ["news", "sport"],
    "creatorIds": ["creator-1", "creator-2"],
    "locality": {
      "city": "York",
      "latitude": 53.959,
      "longitude": -1.081
    },
    "timestamp": 1785672600000,
    "apiEndpoint": "https://api.eu.amazonalexa.com",
    "locale": "en-GB"
  }
}
```

The backend should treat `creatorIds` as the current creator-notification set
for this Alexa user. Store `userId` exactly as supplied because this value is
required in the notification webhook's `alexaUserIds` field.

`categories`, `locality`, `deviceId`, `apiEndpoint`, and `locale` may be used
for future notification targeting, but creator publication matching should use
`creatorIds` and the follow/unfollow events.

### `notification.unsubscribed`

Sent when the listener disables notifications.

```json
{
  "event": "notification.unsubscribed",
  "timestamp": "2026-08-02T12:15:00Z",
  "data": {
    "userId": "amzn1.ask.account.EXAMPLE",
    "listenerId": "hear-listener-id",
    "timestamp": 1785672900000
  }
}
```

The backend must stop including this Alexa user in notification webhook
recipients until another `notification.subscribed` event is received.

## Alexa-to-backend authentication

Alexa sends:

- `Content-Type: application/json`
- `X-Api-Key: <HEAR_API_KEY>`
- `x-webhook-signature: t=<unix-seconds>,v1=<hex-digest>`
- `x-webhook-timestamp: <unix-seconds>`

To verify the request:

1. Parse `t` and `v1` from `x-webhook-signature`.
2. Reject timestamps outside the configured tolerance.
3. Build `<t>.<raw-request-body>` without parsing or re-serializing the body.
4. Calculate HMAC-SHA256 using `WEBHOOK_OUTBOUND_SECRET`.
5. Compare the hexadecimal digest with `v1` using a constant-time comparison.
6. Validate `X-Api-Key` using the configured Hear API key.

Return any `2xx` response only after the event has been durably accepted.
Non-`2xx` responses are retried and eventually sent to the outbound dead-letter
queue.

## Backend-to-Alexa notification webhook

When new content is published, the backend calls the deployed Alexa webhook:

```text
POST <NOTIFICATION_WEBHOOK_URL>
Content-Type: application/json
X-Api-Key: <HEAR_API_KEY>
x-webhook-signature: t=<unix-seconds>,v1=<hmac-sha256>
x-webhook-timestamp: <unix-seconds>
```

`NOTIFICATION_WEBHOOK_URL` is the stack's `NotificationWebhookEndpoint`
CloudFormation output. Its complete path ends in `/webhook/notification`.
The existing `WebhookEndpoint` output ends in `/webhook`, so the equivalent
address is `${WebhookEndpoint}/notification`.

This is not `https://alexa.hear.media/api/v1/alexa/events`; that URL receives
events travelling in the opposite direction, from Alexa to the Hear backend.

### New track

```json
{
  "eventId": "content-published:content-id:1785673200",
  "notificationType": "content",
  "contentId": "content-id",
  "title": "York morning news",
  "alexaUserIds": [
    "amzn1.ask.account.USER_ONE",
    "amzn1.ask.account.USER_TWO"
  ],
  "publishedAt": 1785673200
}
```

### New publication

```json
{
  "eventId": "publication-published:publication-id:1785673200",
  "notificationType": "publication",
  "publicationId": "publication-id",
  "title": "August talking newspaper",
  "alexaUserIds": [
    "amzn1.ask.account.USER_ONE",
    "amzn1.ask.account.USER_TWO"
  ],
  "publishedAt": 1785673200
}
```

### Field contract

| Field | Required | Contract |
|---|---:|---|
| `eventId` | yes | Stable, unique publication event identifier used for idempotency. |
| `notificationType` | yes | Exactly `content` or `publication`. |
| `contentId` | conditional | Required for `content`; must be omitted for `publication`. |
| `publicationId` | conditional | Required for `publication`; must be omitted for `content`. |
| `title` | no | Human-readable title; defaults to `a new recording`. |
| `creatorId` | recommended | Stable creator identifier used for grouping and auditing. |
| `creatorName` | recommended | Human-readable creator used in inbox and proactive speech. |
| `organizationId` | no | Stable publisher organisation identifier. |
| `alexaUserIds` | yes | Non-empty array of subscribed Alexa user IDs. |
| `publishedAt` | no | Unix time in seconds; defaults to receipt time. |

Exactly one of `contentId` and `publicationId` must be supplied. Recipient IDs
are deduplicated by the Alexa webhook.

The backend should send only users who:

1. currently follow the content's creator;
2. have an active notification subscription; and
3. have not subsequently sent `user.unfollowed_creator` or
   `notification.unsubscribed`.

Split very large recipient sets into bounded batches, but reuse the same
`eventId` for every batch belonging to the same publication event. Alexa's
idempotency key is `eventId + alexaUserId`, so retrying a batch is safe.

### Responses

Successful response:

```json
{
  "status": "ok",
  "recipients": 2
}
```

| Status | Meaning |
|---:|---|
| `200` | Notification records were accepted. |
| `400` | Invalid JSON, missing fields, invalid type, or invalid ID combination. |
| `401` | API key or HMAC signature is missing or incorrect. |
| `409` | The signed request was already received within the replay window. |
| `404` | Incorrect webhook path. |
| `500` | Alexa webhook failed internally; retry with backoff. |

The backend should retry `500`, `503`, and network failures with exponential backoff.
It should not retry `400`, `401`, `404`, or `409` until the request or configuration
has been corrected.

## Playback behavior

After the listener accepts the offer:

- content notifications are resolved in one search using `contentIds`;
- one publication notification is resolved using `publicationIds`;
- the resulting recordings are added to the Alexa playback queue;
- a record remains pending until Alexa receives `AudioPlayer.PlaybackStarted`;
- failed playback returns a queued content notification to pending;
- inbox records expire after seven days.

The backend does not need to mark notification records as consumed. That
lifecycle is owned by the Alexa application.

## Proactive Alexa delivery

Production notification requests are split into recipient batches and placed
on `NotificationIngestQueue`. The consumer creates idempotent inbox records and
sends `AMAZON.MessageAlert.Activated` to Alexa's Proactive Events API for each
recipient. Its stable reference ID is derived from `eventId + alexaUserId`.

Configure these SSM SecureString parameters before production deployment:

```text
/hear/<stage>/ALEXA_PROACTIVE_CLIENT_ID
/hear/<stage>/ALEXA_PROACTIVE_CLIENT_SECRET
```

The Alexa skill manifest must declare
`AMAZON.MessageAlert.Activated`, include
`alexa::devices:all:notifications:write`, and pass Amazon certification.
Without credentials the inbox is still created, but proactive delivery is
recorded as `not_configured`.

Inbox state and delivery state are independent:

```text
status: pending -> offered -> resolving -> queued -> consumed
deliveryStatus: pending -> sent | not_configured
```

The webhook accepts at most 5,000 recipients and creates SQS batches of 100.
For larger audiences, the backend sends multiple requests with the same
`eventId`; inbox idempotency is `eventId + alexaUserId`.

## Inbound authentication

Production no longer accepts the shared `x-webhook-secret` header by itself.
Sign the exact raw JSON body using the same timestamped HMAC format as outbound
Alexa events. Send `X-Api-Key`, `x-webhook-signature`, and
`x-webhook-timestamp`. Requests outside the signature tolerance or repeated
within the replay window are rejected. The legacy secret is available only
when `WEBHOOK_ALLOW_LEGACY_SECRET=1`, which production sets to `0`.

## Backend implementation checklist

- Accept and verify the four outbound event types.
- Store the exact Alexa `userId`, Hear listener ID, notification opt-in state,
  and followed creator IDs.
- Make every event handler idempotent.
- Remove recipients immediately after unfollow or unsubscribe events.
- Resolve recipients when a track or publication becomes publicly playable.
- Do not notify for drafts, scheduled-but-unpublished items, or inaccessible
  recordings.
- Send the content or publication identifier used by the Alexa search API.
- Authenticate inbound requests with API key and timestamped HMAC.
- Log `eventId`, notification type, recipient count, HTTP status, and retry
  attempt without logging full Alexa user IDs.
- Alert on repeated `401`, `404`, or `500` responses.
