# Alexa Notification Delivery Plan

## Final Model

There are only two notification types:

- `organization_update`
- `creator_update`

A notification describes one source update. It can belong to one listener or
one million listeners.

The Alexa service uses only `listenerId` for recipient identity. It never
fetches or updates a notification by Alexa user ID.

The Alexa service does not resolve followers, query Meilisearch directly, or
store notifications in DynamoDB. Every notification operation goes through:

```http
POST /alexa/notification
```

## Meilisearch Data Structure

Do not store one million listener IDs inside one notification document. Use one
small source-update document and one small recipient-state document per
listener. This allows each listener to be queried, delivered, retried, and
updated independently.

### 1. Source update document

Store this once for the creator or organization update:

```json
{
  "id": "creator-update-18-20260910T150500Z",
  "schemaVersion": 1,
  "notificationId": "creator-update-18-20260910T150500Z",
  "notificationType": "creator_update",
  "sourceType": "creator",
  "sourceId": "creator-18",
  "sourceName": "Jordan Lee",
  "lastDate": "2026-09-10T15:05:00Z",
  "expiresAt": "2026-09-11T15:05:00Z"
}
```

Organization example:

```json
{
  "id": "organization-update-42-20260910T142000Z",
  "schemaVersion": 1,
  "notificationId": "organization-update-42-20260910T142000Z",
  "notificationType": "organization_update",
  "sourceType": "organization",
  "sourceId": "organization-42",
  "sourceName": "Pendle Voice",
  "lastDate": "2026-09-10T14:20:00Z",
  "expiresAt": "2026-09-11T14:20:00Z"
}
```

There is no track payload, publication payload, `contentId`, `publicationId`,
audio URL, or copied catalog record.

### 2. Recipient-state document

Create one small document for every listener that should receive the update:

```json
{
  "id": "7cb684dc8e2f...",
  "notificationId": "creator-update-18-20260910T150500Z",
  "listenerId": "listener-7",
  "dispatchShard": 41,
  "deliveryStatus": "pending",
  "inboxStatus": "pending",
  "attemptCount": 0,
  "nextAttemptAt": "2026-09-10T15:05:00Z",
  "leaseUntil": null,
  "expiresAt": "2026-09-11T15:05:00Z"
}
```

Rules:

- `id = SHA-256(notificationId:listenerId)`.
- `listenerId` is the only stored recipient identifier.
- `dispatchShard = SHA-256(listenerId) modulo 256`.
- The source-update fields are not duplicated into every recipient document.
- Each listener has independent delivery and inbox status.

For one million recipients, this produces one source-update document and one
million small recipient-state documents. It does not produce one oversized
document containing a million-element array.

## Data Returned to This Alexa Service

### Scheduled dispatch page

EventBridge invokes the loader every minute. The loader requests one bounded
page:

```json
{
  "operation": "dispatch",
  "shard": 41,
  "dueBefore": "2026-09-10T15:06:00Z",
  "limit": 1000
}
```

The endpoint returns one notification and an array containing only listener
IDs:

```json
{
  "notification": {
    "notificationId": "creator-update-18-20260910T150500Z",
    "notificationType": "creator_update",
    "sourceType": "creator",
    "sourceId": "creator-18",
    "sourceName": "Jordan Lee",
    "lastDate": "2026-09-10T15:05:00Z",
    "expiresAt": "2026-09-11T15:05:00Z"
  },
  "listenerIds": [
    "listener-7",
    "listener-8",
    "listener-9"
  ],
  "hasMore": true
}
```

`listenerIds` is capped at 1,000 entries per response. When `hasMore=true`, the
loader requests the same shard again. The endpoint has already leased the
returned recipient documents, so the next request returns the next pending
page.

The array exists only as a bounded API response. It is not stored as one giant
array in Meilisearch.

## SQS Structure

The loader creates one FIFO SQS message for every listener ID:

```json
{
  "schemaVersion": 1,
  "notificationId": "creator-update-18-20260910T150500Z",
  "listenerId": "listener-7"
}
```

No Alexa user ID, source data, track data, publication data, or recipient array
is placed in the SQS message.

Queue identity:

```text
MessageGroupId         = listenerId
MessageDeduplicationId = SHA-256(notificationId:listenerId)
```

One message per listener gives each listener an independent retry and status.
A failure for one listener never retries deliveries that already succeeded for
other listeners.

## Fetching the Delivery Payload

The delivery worker fetches the exact notification using only the IDs from SQS:

```json
{
  "operation": "fetch",
  "notificationId": "creator-update-18-20260910T150500Z",
  "listenerId": "listener-7",
  "purpose": "delivery"
}
```

The endpoint returns the joined source update and a transient Alexa delivery
target:

```json
{
  "notification": {
    "notificationId": "creator-update-18-20260910T150500Z",
    "notificationType": "creator_update",
    "sourceType": "creator",
    "sourceId": "creator-18",
    "sourceName": "Jordan Lee",
    "lastDate": "2026-09-10T15:05:00Z",
    "expiresAt": "2026-09-11T15:05:00Z"
  },
  "listenerId": "listener-7",
  "deliveryTarget": {
    "type": "alexa",
    "userId": "amzn1.ask.account.example"
  }
}
```

The Alexa user ID is never a recipient lookup key and never appears in the
recipient document or SQS message. It is returned only at the final delivery
step because the Alexa Proactive Events API requires it to address the user.

## Delivery Update

After Alexa accepts or rejects the event, update only that listener:

```json
{
  "operation": "update",
  "notificationId": "creator-update-18-20260910T150500Z",
  "listenerId": "listener-7",
  "deliveryStatus": "sent",
  "deliveryHttpStatus": 202
}
```

The unique update key is always:

```text
notificationId + listenerId
```

Never mark the shared source-update document as sent for every listener.

```text
Delivery: pending -> leased -> sent | retrying | suppressed | failed
Inbox:    pending -> offered -> consumed | dismissed
```

## Listener Checks Notifications

When the listener opens the skill or asks for notifications:

```json
{
  "operation": "fetch",
  "listenerId": "listener-7",
  "purpose": "inbox",
  "limit": 5
}
```

The endpoint filters recipient-state documents by `listenerId`, joins their
source updates, and returns the notification payloads. Fetching by Alexa user ID
is not supported.

Alexa says:

> Good news, you've got a new release from {sourceName}. Would you like to
> listen?

### Organization update: yes

```json
{
  "q": "",
  "sort": "latest",
  "limit": 10,
  "filter": {
    "organizationIds": ["organization-42"],
    "publishedFrom": "2026-09-10T14:20:00Z"
  }
}
```

### Creator update: yes

```json
{
  "q": "",
  "sort": "latest",
  "limit": 10,
  "filter": {
    "creatorIds": ["creator-18"],
    "publishedFrom": "2026-09-10T15:05:00Z"
  }
}
```

The catalog decides what playable results belong to the update. Mark
`inboxStatus=consumed` only after playback begins.

When the listener says no, update `notificationId + listenerId` with
`inboxStatus=dismissed`.

## Million-Recipient Delivery

For one notification targeting one million listeners:

1. Store one source-update document.
2. Store one million small recipient-state documents distributed over 256
   `dispatchShard` values.
3. EventBridge starts the loader every minute.
4. The loader requests batches of at most 1,000 listener IDs from each shard.
5. The loader sends one million small SQS messages in batches of 10.
6. SQS holds the burst and invokes delivery workers within the configured Alexa
   concurrency limit.
7. Every worker fetches and updates using `notificationId + listenerId`.

This structure scales because no request, document, or SQS message contains all
one million recipients.

## Reliability Rules

- Use FIFO SQS and the hash of `notificationId:listenerId` as both the SQS
  deduplication ID and Alexa proactive `referenceId`.
- Return partial-batch failures so only failed listeners retry.
- Retry transient endpoint and Alexa errors with backoff and jitter.
- Expired leases return recipient documents to `pending`.
- Move a delivery to a 14-day DLQ after five failed receives.
- Cap Lambda concurrency at the approved Alexa proactive-event rate.
- Monitor pending recipient count, loader throughput, queue age and depth,
  delivery success, retry count, expired leases, and DLQ depth.

## Acceptance Criteria

- Recipient arrays contain only `listenerId` values.
- Recipient-state documents contain only `listenerId` as recipient identity.
- SQS messages contain only `notificationId`, `listenerId`, and schema version.
- Notification fetch and update use `listenerId`; Alexa user ID is never a
  lookup filter.
- Only `creator_update` and `organization_update` exist.
- No notification DynamoDB table, follower filtering, or direct Meilisearch
  access exists in the Alexa service.
- Every listener has independent delivery, retry, inbox, and failure state.
- No single document or request contains an unbounded recipient list.
