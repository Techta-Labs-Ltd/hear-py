# Notification Architecture: Million-Listener Scale with Priority

## Goal

Deliver useful Hear notifications to potentially one million listeners without placing large recipient lists in one document, losing priority information, duplicating proactive events, or allowing one listener's failure to block another listener.

Supported notification subjects:

- publication update;
- organization update;
- creator update.

The backend owns notification creation, follower resolution, ranking, leasing, retry policy, and recipient state. The Alexa skill owns final Alexa delivery and in-skill playback/inbox behavior.

This design does not require DynamoDB. The source and recipient state may live
in the backend's existing transactional database, such as PostgreSQL, with
proper indexes and partitioning. EventBridge and SQS carry commands and events;
they are not the system of record.

## Core Rule

A notification is split into:

1. one immutable source-update record;
2. one small recipient-state record per listener;
3. one SQS message per listener delivery attempt.

Never store one million listener IDs in one notification document.

## Identity and Deduplication

The canonical recipient identity is always `listenerId`.

Alexa's `alexaUserId` is resolved only at final delivery because the Alexa Proactive Events API requires it. It is not the primary backend lookup key and must not be used for follower fan-out.

The unique delivery key is:

```text
notificationId:listenerId
```

Use a stable hash of that value for:

- recipient-state record ID;
- SQS deduplication ID when using FIFO SQS;
- Alexa proactive `referenceId`.

The same notification must not be created twice for the same source update. Prefer a deterministic source event ID supplied by the publication/content transaction.

## Source Update Record

Create one immutable source record when new content becomes available.

Publication example:

```json
{
  "notificationId": "publication-update-publication-42-20260916T120000Z",
  "schemaVersion": 2,
  "notificationType": "publication_update",
  "sourceType": "publication",
  "sourceId": "publication-42",
  "sourceName": "The Weekly Review",
  "publicationId": "publication-42",
  "organizationId": "organization-7",
  "organizationName": "Pendle Voice",
  "publishedAt": "2026-09-16T12:00:00Z",
  "lastDate": "2026-09-16T12:00:00Z",
  "expiresAt": "2026-09-17T12:00:00Z",
  "presentation": {
    "title": "A new publication is available",
    "contentName": "The Weekly Review",
    "providerName": "Pendle Voice"
  }
}
```

Creator example:

```json
{
  "notificationId": "creator-update-creator-18-20260916T120000Z",
  "schemaVersion": 2,
  "notificationType": "creator_update",
  "sourceType": "creator",
  "sourceId": "creator-18",
  "sourceName": "Jordan Lee",
  "publishedAt": "2026-09-16T12:00:00Z",
  "lastDate": "2026-09-16T12:00:00Z",
  "expiresAt": "2026-09-17T12:00:00Z",
  "presentation": {
    "title": "A new release from Jordan Lee",
    "contentName": "New release from Jordan Lee",
    "providerName": "Hear"
  }
}
```

The source record must not contain:

- a million-element listener array;
- Alexa user IDs;
- audio URLs;
- copied track lists;
- per-listener delivery state.

## Recipient-State Record

Create one recipient record for each eligible listener.

```json
{
  "id": "sha256(notificationId:listenerId)",
  "schemaVersion": 2,
  "notificationId": "publication-update-publication-42-20260916T120000Z",
  "listenerId": "listener-7",
  "sourceType": "publication",
  "sourceId": "publication-42",
  "priority": 920,
  "priorityBand": "high",
  "priorityReason": "listener_requested_publication",
  "dispatchShard": 41,
  "inboxStatus": "pending",
  "deliveryStatus": "pending",
  "attemptCount": 0,
  "nextAttemptAt": "2026-09-16T12:00:00Z",
  "leaseUntil": null,
  "lastAttemptAt": null,
  "deliveryErrorCode": null,
  "alexaUserId": null,
  "expiresAt": "2026-09-17T12:00:00Z",
  "createdAt": "2026-09-16T12:00:00Z",
  "updatedAt": "2026-09-16T12:00:00Z"
}
```

The source data can be joined at fetch time. Duplicating small display fields is acceptable if it avoids an expensive join, but the recipient record remains bounded and must not contain full content data.

## Priority Model

Priority is calculated by the backend before fan-out. The Alexa worker must not invent or recalculate business priority.

Use a numeric range such as `0..1000`:

- `900..1000`: listener explicitly requested this source or publication;
- `700..899`: listener follows the source and has recently listened;
- `500..699`: listener follows the source;
- `300..499`: organization-wide or broad recommendation;
- `0..299`: low-value or catch-up notification.

Priority should be based on explicit fields, not an opaque score only. Store both:

```json
{
  "priority": 920,
  "priorityBand": "high",
  "priorityReason": "listener_requested_publication"
}
```

Recommended ranking inputs:

- explicit publication subscription;
- explicit organization follow;
- explicit creator follow;
- recent listening to the source;
- notification frequency limit;
- listener quiet hours and timezone;
- source type;
- age of the content;
- whether an equivalent notification is already pending;
- whether the listener recently dismissed the same source.

Priority must not override safety and delivery rules. A high-priority item still needs valid Alexa notification permission, a valid delivery target, and a non-expired lease.

## Avoiding Notification Spam

Before creating a new recipient record, deduplicate by listener and logical source window.

Recommended logical key:

```text
listenerId + sourceType + sourceId + publication/date window
```

Examples:

- one publication notification per publication release;
- one creator notification per content release window;
- one organization notification per publication release window.

If one publication matches both an organization follow and a publication follow, create one recipient record and retain the highest priority plus a list of reasons if needed:

```json
{
  "priority": 950,
  "priorityReason": "listener_requested_publication",
  "matchedRules": [
    "publication_follow",
    "organization_follow"
  ]
}
```

## Backend Trigger Flow

Use an event-driven trigger from the publication/content transaction.

```text
content published
    -> durable domain event
    -> notification planner
    -> source-update record
    -> follower/subscriber resolution
    -> priority calculation
    -> recipient-state records
    -> dispatch queue messages
    -> Alexa delivery worker
```

The publication transaction must commit before the notification planner runs. Use an outbox or durable event bus so a database commit cannot succeed while the notification event is lost.

The planner must be restartable and idempotent:

1. derive deterministic `notificationId` from the source event;
2. upsert the source record conditionally;
3. page through eligible listeners;
4. conditionally create recipient records;
5. enqueue only records successfully created or leased;
6. record progress with a cursor.

Do not resolve one million followers in one Lambda invocation.

## Admin Publish and Scheduler Integration

The admin application must not send one million notifications synchronously and
must not call the Alexa Proactive Events API directly. It should commit the
content change and a durable outbox event in the same database transaction.

Admin publish event:

```json
{
  "eventType": "content.published",
  "eventId": "publish-event-123",
  "contentId": "track-42",
  "publicationId": "publication-9",
  "organizationId": "organization-7",
  "creatorId": "creator-3",
  "publishedAt": "2026-09-16T12:00:00Z"
}
```

The event must be written atomically with the publication/content transaction:

```text
admin publish request
    -> save content
    -> save content.published outbox event
    -> commit transaction
    -> notification planner consumes event
```

Use an EventBridge Scheduler recurring trigger for the planner, for example
every minute. The scheduler should trigger bounded planning work, not one
schedule per listener or one schedule per notification recipient.

```text
EventBridge Scheduler
    -> NotificationPlanner Lambda
    -> planner reads durable outbox/domain events
    -> planner creates source update
    -> planner pages eligible listeners
    -> planner writes recipient state
    -> planner sends SQS messages
```

The planner must keep a cursor or continuation token. A million-recipient
notification is processed as many bounded pages, such as 1,000 listeners per
invocation, until the event is complete.

The planner should expose or call an internal operation equivalent to:

```http
POST /internal/notification-dispatch/plan
```

```json
{
  "eventId": "publish-event-123",
  "notificationId": "publication-update-publication-9-20260916T120000Z",
  "dispatchShard": 41,
  "cursor": "next-page-token",
  "limit": 1000
}
```

The scheduler is a trigger only. It must not be treated as the source of truth
for notification state. If a scheduler invocation is delayed or repeated, the
outbox event and conditional recipient writes make the operation resumable and
idempotent.

EventBridge does not know which user a notification belongs to. It must never
be given a broad event and trusted to discover recipients during delivery. The
planner resolves the exact listener relationship first, then emits one message
containing the exact `notificationId` and `listenerId` pair. This is the point
where recipient targeting is enforced.

Recommended EventBridge Scheduler input:

```json
{
  "operation": "plan_due_notifications",
  "shard": 41,
  "limit": 1000,
  "dueBefore": "2026-09-16T12:01:00Z"
}
```

The scheduler input contains a shard and a bounded page, not a user list. The
planner reads the backend database, applies eligibility and priority rules, and
publishes only authorized recipient messages.

## Recipient Eligibility and Final Protection

The planner must create a recipient record only when all backend eligibility
checks pass:

- the listener follows or subscribes to the relevant creator, organization, or
  publication;
- notifications are enabled for that listener;
- the source is not muted by the listener;
- the notification is inside its delivery window;
- quiet hours and listener timezone rules allow delivery, or the item is held
  until `nextAttemptAt`;
- the listener has not already received or dismissed the same logical update;
- the notification is not superseded by a newer equivalent update.

Eligibility is evaluated from backend listener relationships. It must not be
inferred from an Alexa request or from a broad recipient list.

The delivery worker must repeat the security-sensitive checks immediately
before sending. Fetching a recipient record from SQS is not authorization by
itself. The backend fetch response must verify that:

```text
notificationId belongs to listenerId
deliveryStatus is still deliverable
the notification has not expired
the listener still has notification permission
the Alexa delivery target is current
```

If the final check fails, return a non-retryable result and mark the recipient
`suppressed`. Never retry a recipient indefinitely when the listener is not an
eligible target.

The SQS message must contain only the exact recipient pair and backend-ranked
priority:

```json
{
  "schemaVersion": 2,
  "notificationId": "publication-update-publication-9-20260916T120000Z",
  "listenerId": "listener-55",
  "priority": 950
}
```

It must not contain a general recipient list, unrelated listener IDs, audio
URLs, profile data, or access tokens.

## Priority Dispatch

Priority is calculated once by the backend planner and stored on recipient
state. The Alexa worker does not recalculate business priority.

Recommended priority bands:

```text
900-1000  explicit publication subscription or request
700-899   followed source with recent listening
500-699   ordinary creator or organization follow
300-499   broad organization update
0-299     low-priority catch-up item
```

If a listener matches multiple rules, create one recipient record, retain the
highest priority, and record the matched rules for auditability:

```json
{
  "priority": 950,
  "priorityReason": "publication_subscription",
  "matchedRules": [
    "publication_subscription",
    "organization_follow"
  ]
}
```

Do not rely on ordinary SQS ordering to implement priority. Use separate
high-, normal-, and low-priority queues, or have the planner lease due
recipient records in priority order. In either design, apply concurrency caps
so high priority does not exceed Alexa's approved proactive-event rate.

## What This Repository Already Provides

The Alexa repository currently provides:

- `ProactiveNotificationQueue` and its dead-letter queue;
- `main.notification_handler`;
- final notification fetch through `/alexa/notification`;
- Alexa LWA token handling;
- proactive event submission;
- partial-batch failure reporting;
- delivery status updates;
- in-skill notification inbox and playback status handling.

The backend still needs to provide:

- admin publish outbox/domain events;
- source-update creation;
- follower/subscriber eligibility resolution;
- priority calculation;
- per-listener recipient-state storage;
- scheduler-driven paged fan-out;
- leasing and lease recovery;
- priority queue publishing;
- conditional deduplication and final authorization checks.

The existing Alexa notification worker should remain a delivery worker, not
become the million-listener fan-out engine.

## Required Alexa Playback Correlation Update

The current skill already includes `listenerId` and `alexaUserId` on outbound
playback events when canonical identity and request identity are available.
That lets the backend identify the listener, but it does not yet identify which
notification caused the playback.

The missing correlation field is:

```json
{
  "notificationId": "notification-42"
}
```

Without it, the backend can only know:

```text
listener-7 played content-42
```

It cannot reliably know:

```text
listener-7 listened to notification-42
```

Add notification context at the notification playback boundary:

```text
notification accepted
   -> notificationPlayback stores notificationId + contentId
   -> Playback.start copies notificationId into activePlayback
   -> Playback.emit includes notificationId
   -> existing playback.started/progress/finished/failed events reach backend
```

For publication notifications, retain all relevant identifiers:

```json
{
  "listenerId": "listener-7",
  "notificationId": "notification-42",
  "publicationId": "publication-9",
  "contentId": "track-42",
  "sessionId": "track-42:session-99",
  "eventType": "started"
}
```

For creator or organization notifications, include `notificationId` and the
actual `contentId`, plus source context where available.

The required Alexa-side changes are:

1. extend the transient `notificationPlayback` state to retain notification
  context, not only `notificationId` and `contentId` where more context is
  needed;
2. merge that context into the content passed to the shared playback start
  boundary;
3. persist `notificationId` in `activePlayback` for the playback session;
4. pass it through `OutboundEventService.playback()` into
  `PlaybackUtils.build_playback_event()`;
5. add tests for notification playback started, progress, finished, and failed
  events;
6. ensure ordinary playback leaves `notificationId` absent;
7. clear notification context when playback is replaced by unrelated content.

Do not add a separate `/notification/listened` API. The existing playback event
pipeline is the listening signal. The existing notification update API remains
appropriate for inbox and delivery transitions such as `offered`, `dismissed`,
`sent`, `failed`, and `suppressed`.

The backend should correlate playback events using:

```text
notificationId + listenerId + sessionId
```

It should conditionally transition the recipient state when it receives the
first valid `playback.started` event. Later progress and finish events may
update listening measurements, but must be idempotent and must not reopen a
terminal notification state.

## Storage Without DynamoDB

Use the backend's transactional database as the source of truth. PostgreSQL is
an appropriate implementation when the backend already uses it:

### `notification_source`

One immutable row per source update, uniquely keyed by `notification_id`.

Useful indexes:

```text
unique(notification_id)
index(expires_at)
index(published_at)
```

### `notification_recipient`

One row per listener and notification. Use a deterministic unique key:

```text
unique(notification_id, listener_id)
```

Useful indexes:

```text
index(dispatch_shard, delivery_status, next_attempt_at, priority desc)
index(listener_id, inbox_status, priority desc, published_at desc)
index(lease_until)
```

Partition recipient rows by creation month or dispatch shard when volume
requires it. The important property is transactional conditional updates, not
the database vendor.

The backend may use Redis for short-lived queue acceleration, but Redis must
not replace durable recipient state. EventBridge, SQS, or Redis may lose or
redeliver work; the database state and idempotency key decide what is valid.

## Notification Lifecycle Events

Do not call a notification "listened" when EventBridge fires it or when Alexa
returns HTTP `202`. Those only mean that the delivery request was accepted.

Use separate lifecycle states:

```text
planned
  -> queued
  -> leased
  -> sent                 Alexa accepted proactive request
  -> offered              in-skill inbox announced the item
  -> started              notification content playback started
  -> listened             listener reached the product's listening threshold

sent/offered -> dismissed
sent/offered -> expired
leased -> retrying
leased -> failed
```

Recommended event names:

- `notification.planned`;
- `notification.queued`;
- `notification.sent`;
- `notification.offered`;
- `notification.started`;
- `notification.dismissed`;
- `notification.expired`;
- `notification.failed`.

The backend should publish these events through its durable outbox to an
EventBridge event bus or equivalent. EventBridge delivery is at least once, so
consumers must deduplicate using:

```text
eventId = notificationId:listenerId:eventType:transitionVersion
```

### Proactive sent event

Emit this only after Alexa's proactive API returns `202`:

```json
{
  "detail-type": "notification.sent",
  "source": "hear.notifications",
  "detail": {
    "eventId": "notification-42:listener-7:sent:1",
    "notificationId": "notification-42",
    "listenerId": "listener-7",
    "deliveryStatus": "sent",
    "provider": "alexa_proactive",
    "providerStatus": 202,
    "occurredAt": "2026-09-16T12:01:03Z"
  }
}
```

### In-skill offered event

Emit this when the skill has spoken the inbox offer and the backend update
succeeds:

```json
{
  "detail-type": "notification.offered",
  "source": "hear.notifications",
  "detail": {
    "eventId": "notification-42:listener-7:offered:2",
    "notificationId": "notification-42",
    "listenerId": "listener-7",
    "channel": "skill_launch",
    "occurredAt": "2026-09-16T12:02:00Z"
  }
}
```

## How the Alexa Worker Reports Back

The existing worker already updates the backend after proactive delivery. The
backend should make those status updates transactional and publish the
corresponding lifecycle event from its own outbox:

```text
Alexa worker receives 202
    -> POST /alexa/notification update deliveryStatus=sent
    -> backend conditional state transition
    -> backend outbox writes notification.sent
    -> EventBridge event bus delivers notification.sent
```

For in-skill notifications:

```text
LaunchRequest or HearNotificationsIntent
    -> POST /alexa/notification fetch purpose=inbox
    -> skill speaks the offer
    -> POST /alexa/notification update inboxStatus=offered
    -> backend outbox writes notification.offered

user says yes
    -> skill resolves current content
    -> AudioPlayer.PlaybackStarted
    -> existing playback.started event includes notificationId when applicable
    -> backend correlates notificationId + listenerId
    -> backend conditionally updates inboxStatus=started
    -> backend may derive listening measurements from playback.progress events
```

The update endpoint must require both `notificationId` and `listenerId`, verify
that the pair exists, and apply an allowed state transition conditionally. A
request for a different listener must return `404` or `409` and must not update
any record.

The current Alexa adapter already marks an in-skill notification `consumed` when
`AudioPlayer.PlaybackStarted` arrives. Keep that transition, but use a clear
backend state name such as `started` or `consumed` consistently. The playback
event must carry notification context so the backend can associate the event
with the exact recipient without a new API call.

## EventBridge Rules

Use separate EventBridge responsibilities:

1. **EventBridge Scheduler** invokes the planner periodically with shard/page
   input.
2. **EventBridge Event Bus** transports durable lifecycle events such as
  `notification.sent`, `notification.offered`, and `notification.started`.
3. **SQS** carries per-recipient delivery work and handles retry/backpressure.

Do not use an EventBridge event as a substitute for a per-listener delivery
message. EventBridge fan-out rules can accidentally broadcast an event to
consumers that do not own the recipient relationship. Recipient authorization
must happen in the planner and again in the final backend fetch.

The existing playback event consumer remains the source of truth for listening
activity. When a playback event contains notification context, the backend
updates the recipient row and may publish `notification.started` or another
internal analytics event through the EventBridge event bus. This is derived
from the existing playback stream; it is not a new notification API.

## Fan-Out at Million Scale

Partition recipient discovery by stable shards:

```text
dispatchShard = hash(listenerId) modulo 256
```

Use a bounded worker loop per shard. Each invocation processes a limited page, for example 1,000 listeners, then stores a cursor or schedules the next page.

For each listener:

```json
{
  "schemaVersion": 2,
  "notificationId": "publication-update-publication-42-20260916T120000Z",
  "listenerId": "listener-7",
  "priority": 920
}
```

Do not put full source data or a listener array in SQS.

A standard SQS queue is sufficient if the backend owns idempotency and recipient state. Use FIFO only if strict per-listener ordering is a real product requirement and the throughput/cost tradeoff is acceptable. If FIFO is used:

```text
MessageGroupId = listenerId
MessageDeduplicationId = sha256(notificationId:listenerId)
```

Priority queues are usually clearer than one queue with strict priority. Recommended queues:

- `high-priority-notifications`;
- `normal-priority-notifications`;
- `low-priority-notifications`.

Alternatively, use one queue with `priority` stored in recipient state and have the dispatcher lease highest-priority due records first. Do not rely on SQS message order to implement priority.

## Leasing and Concurrency

Before enqueueing or delivering, claim the recipient record with a conditional update:

```text
status = pending or retrying
nextAttemptAt <= now
leaseUntil is null or leaseUntil < now
```

Set:

```text
status = leased
leaseUntil = now + 2 minutes
attemptCount = attemptCount + 1
```

The lease must expire automatically or be reclaimed by a scheduled recovery worker. A crashed worker must not strand a notification forever.

The delivery worker must conditionally transition states. For example:

```text
leased -> sent
leased -> retrying
leased -> failed
leased -> suppressed
```

A late worker must not overwrite a newer terminal state.

## Backend-to-Alexa Fetch Contract

The current skill pattern is appropriate: SQS contains only IDs, then the worker fetches the exact joined notification.

Request:

```json
{
  "operation": "fetch",
  "purpose": "delivery",
  "notificationId": "publication-update-publication-42-20260916T120000Z",
  "listenerId": "listener-7"
}
```

Response:

```json
{
  "schemaVersion": 2,
  "notification": {
    "notificationId": "publication-update-publication-42-20260916T120000Z",
    "notificationType": "publication_update",
    "sourceType": "publication",
    "sourceId": "publication-42",
    "sourceName": "The Weekly Review",
    "publicationId": "publication-42",
    "organizationId": "organization-7",
    "organizationName": "Pendle Voice",
    "lastDate": "2026-09-16T12:00:00Z",
    "expiresAt": "2026-09-17T12:00:00Z",
    "presentation": {
      "title": "A new publication is available",
      "contentName": "The Weekly Review",
      "providerName": "Pendle Voice"
    }
  },
  "listenerId": "listener-7",
  "deliveryTarget": {
    "type": "alexa",
    "userId": "amzn1.ask.account.example",
    "locale": "en-GB",
    "notificationsPermission": true
  }
}
```

The backend should return no delivery target when permission is absent or the target is stale. The worker should mark the recipient `suppressed`, not retry permanently.

## Alexa Proactive Event

Use `AMAZON.MediaContent.Available` for an available publication or release.

The payload should be generated from explicit presentation fields:

```json
{
  "timestamp": "2026-09-16T12:01:00Z",
  "referenceId": "sha256(notificationId:listenerId)",
  "expiryTime": "2026-09-17T12:00:00Z",
  "event": {
    "name": "AMAZON.MediaContent.Available",
    "payload": {
      "availability": {
        "startTime": "2026-09-16T12:00:00Z",
        "provider": {
          "name": "localizedattribute:providerName"
        },
        "method": "STREAM"
      },
      "content": {
        "name": "localizedattribute:contentName",
        "contentType": "EPISODE"
      }
    }
  },
  "localizedAttributes": [
    {
      "locale": "en-GB",
      "providerName": "Pendle Voice",
      "contentName": "The Weekly Review"
    }
  ],
  "relevantAudience": {
    "type": "Unicast",
    "payload": {
      "user": "amzn1.ask.account.example"
    }
  }
}
```

The Alexa event should not contain a full audio URL. When the listener opens the skill, the skill fetches current catalog content by source ID and date.

## In-Skill Inbox Flow

When the listener launches the skill or asks for notifications:

```json
{
  "operation": "fetch",
  "purpose": "inbox",
  "listenerId": "listener-7",
  "limit": 5
}
```

The backend returns items ranked by:

1. priority descending;
2. published date descending;
3. notification creation time descending.

The skill offers the highest-ranked item first:

```text
Good news. A new publication from Pendle Voice is available. Would you like to listen?
```

Status transitions:

```text
pending -> offered -> consumed | dismissed
```

For acceptance:

1. mark `resolving`;
2. search current content by source ID and `publishedFrom`;
3. play the first valid result;
4. mark `queued` after the play directive is prepared;
5. mark `consumed` only after `AudioPlayer.PlaybackStarted`.

For decline, mark `dismissed`.

If playback fails, return the item to `pending` only when the failure is retryable.

## Delivery Status and Retries

The notification worker should return partial batch failures. One failed listener must not retry successful listeners in the same batch.

Retryable conditions:

- network timeout;
- Alexa 429;
- Alexa 5xx;
- backend 429 or 5xx;
- temporary token failure.

Non-retryable conditions:

- missing Alexa user ID;
- notification permission absent;
- expired notification;
- invalid notification schema;
- Alexa permanent rejection;
- listener no longer exists.

Recommended retry schedule:

```text
attempt 1: 1 minute
attempt 2: 5 minutes
attempt 3: 30 minutes
attempt 4: 2 hours
attempt 5: 12 hours
```

Use jitter and cap retries by notification expiry. After the final retry, mark `failed` and place the message in a DLQ for investigation.

## Observability

Track metrics by notification type, priority band, and source type:

- source updates created;
- recipients planned;
- recipients deduplicated;
- recipients leased;
- messages enqueued;
- proactive events accepted;
- proactive events rejected;
- suppressed due to permission or missing target;
- retries;
- expired leases;
- expired notifications;
- inbox offers;
- consumed notifications;
- dismissed notifications;
- playback failures;
- DLQ messages;
- queue age and depth;
- delivery latency by priority band.

Never log Alexa client secrets, access tokens, email addresses, or full delivery payloads containing user identifiers.

## Required Backend APIs

### Create or plan a source update

This should normally be an internal event or service call, not exposed to Alexa.

```http
POST /internal/notification-plans
```

### Lease a bounded dispatch page

```http
POST /internal/notification-dispatch/lease
```

Request:

```json
{
  "notificationId": "publication-update-publication-42-20260916T120000Z",
  "dispatchShard": 41,
  "limit": 1000,
  "leaseSeconds": 120
}
```

### Fetch exact delivery payload

```http
POST /alexa/notification
```

### Update recipient status

```http
POST /alexa/notification
```

Request:

```json
{
  "operation": "update",
  "listenerId": "listener-7",
  "notificationId": "publication-update-publication-42-20260916T120000Z",
  "deliveryStatus": "sent",
  "deliveryHttpStatus": 202
}
```

### Fetch inbox

```http
POST /alexa/notification
```

Request:

```json
{
  "operation": "fetch",
  "purpose": "inbox",
  "listenerId": "listener-7",
  "limit": 5
}
```

## Implementation Order

1. Extend notification schema and normalizer for `publication_update`.
2. Add explicit publication search filtering in the notification acceptance workflow.
3. Add presentation fields so proactive wording is source-specific.
4. Implement backend source-update and recipient-state storage.
5. Implement deterministic fan-out with 256 shards and bounded leases.
6. Add priority calculation and deduplication before queue enqueue.
7. Add high/normal/low dispatch queues or a priority-aware leasing service.
8. Add conditional status transitions and lease recovery.
9. Keep the existing delivery Lambda, partial-batch handling, and DLQ model.
10. Add end-to-end tests for one listener, one thousand listeners, duplicate planning, retries, permission suppression, publication playback, and a simulated million-recipient fan-out using paged fixtures.

## Acceptance Criteria

- One source update can target one million listeners without a large document or request.
- A listener receives at most one proactive event for one notification.
- Higher-priority notifications are dispatched before lower-priority notifications when due.
- One listener failure does not retry successful listeners.
- Expired or permission-disabled notifications are suppressed without infinite retry.
- Publication, organization, and creator updates use the correct catalog filter when accepted in skill.
- Inbox ordering is priority-first and deterministic.
- Every state transition is conditional and idempotent.
- Delivery and inbox status remain independent.
- Playback events contain `listenerId` and notification context when playback
  originated from a notification.
- A notification playback `started` event can be correlated without a new
  listened API.
- Ordinary non-notification playback does not receive a notification ID.
- Queue depth, latency, retries, leases, and DLQ failures are observable.
