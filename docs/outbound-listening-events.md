# Outbound listening and feedback events

## Delivery path

Production delivery is asynchronous:

```text
Alexa AudioPlayer or feedback handler
  -> Hear skill Lambda
  -> SQS outbound queue
  -> Hear outbound Lambda
  -> POST https://alexa.hear.media/api/v1/alexa/events
```

The skill Lambda publishes through `src/services/outbound_dispatch.py`. The
queue and worker are declared in `template.yaml`. The worker entry point is
`src.webhooks.outbound_consumer.handler`.

`SQS_OUT_QUEUE_URL` selects the production queue transport. If it is absent,
`WEBHOOK_OUTBOUND_URL` is used directly. Production configures both and gives
the queue priority.

## Playback events

The following webhook event names are emitted:

- `playback.started`
- `playback.progress`
- `playback.nearly_finished`
- `playback.finished`
- `playback.stopped`
- `playback.paused`
- `playback.failed`

Example envelope:

```json
{
  "event": "playback.progress",
  "timestamp": "2026-08-02T12:00:00Z",
  "data": {
    "contentId": "content-id",
    "creatorId": "creator-id",
    "publicationId": "publication-id",
    "queueId": "queue-id",
    "sessionId": "content-id:session-id",
    "eventType": "progress",
    "positionMs": 90000,
    "durationMs": 180000,
    "listenedMs": 90000,
    "completionPercentage": 50,
    "timestampMs": 1785672000000,
    "clientEventId": "content-id:session-id:progress:1785672000000",
    "alexaUserId": "alexa-user-id",
    "listenerId": "listener-id"
  }
}
```

## Feedback events

Completed recordings can produce `feedback.given`. Its `feedback` value is one
of `enjoyed`, `somewhat`, `not_enjoyed`, or `skipped`.

```json
{
  "event": "feedback.given",
  "timestamp": "2026-08-02T12:05:00Z",
  "data": {
    "alexaUserId": "alexa-user-id",
    "feedbackKey": "content-id",
    "contentId": "content-id",
    "publicationId": "publication-id",
    "creatorId": "creator-id",
    "listenedMs": 180000,
    "feedback": "enjoyed",
    "timestamp": 1785672300000
  }
}
```

## Authentication

The worker signs the exact JSON request body using HMAC-SHA256 and
`WEBHOOK_OUTBOUND_SECRET`. It sends:

- `Content-Type: application/json`
- `x-webhook-signature: t=<unix-seconds>,v1=<hex-digest>`
- `x-webhook-timestamp: <unix-seconds>`

The receiving API must verify the signature against the raw request body and
reject timestamps outside `WEBHOOK_SIGNATURE_TOLERANCE_SECONDS`.

## AWS verification

1. Open the `hear-webhook-out-python-<stage>` SQS queue and check that sent
   messages increase when playback events occur.
2. Open the CloudWatch log group for `Hear-Outbound-Python-<short-stage>`.
3. Search for `Hear outbound webhook delivered`. Each successful entry includes
   the event name, SQS message ID, and backend HTTP status.
4. Search for `Hear outbound webhook failed` to find HTTP, signature, timeout,
   or backend errors.
5. Check `ApproximateAgeOfOldestMessage` and
   `ApproximateNumberOfMessagesVisible` on the outbound queue.
6. Inspect `hear-webhook-out-python-<stage>-dlq`. A message reaches this queue
   after five failed deliveries.
7. Confirm the backend endpoint logs the same `clientEventId`. This is the
   idempotency key for duplicate SQS delivery.

If the worker reports that the webhook URL is not configured, verify
`WEBHOOK_OUTBOUND_URL` on the outbound Lambda. Production currently sets it to
`https://alexa.hear.media/api/v1/alexa/events` in `template.yaml`.

## Retry behavior

The SQS worker returns failed message IDs through Lambda partial-batch failure
reporting. Successful messages are removed. Failed messages are retried and
move to the dead-letter queue after `maxReceiveCount: 5`.
