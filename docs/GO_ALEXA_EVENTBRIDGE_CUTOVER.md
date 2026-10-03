# Alexa source notifications: coordinated Go cutover

## Ownership

Go in the existing hear-catalog-sync-go repository owns catalog-confirmed source
preparation, source-specific Redis projection, follow/history audience ranking,
recoverable RabbitMQ source jobs and EventBridge publishing. The existing
hear-py recipient Lambda alone calls Amazon Proactive Events. Firebase/FCM is
separate and unchanged. No Alexa launch or in-skill prompt behaviour is changed.

Flow: catalog confirmation -> durable source outbox -> Go relay -> RabbitMQ ->
Go source worker -> EventBridge -> source SQS -> small AWS source-page adapter ->
authenticated backend bridge -> Go audience API -> existing recipient SQS ->
existing Amazon sender Lambda. The AWS source adapter does not implement ranking.
It only fetches bounded pages, sends the existing recipient messages and saves
conditional page receipts/cursors. Python backend never sends to AWS in this flow.

The EventBridge contract remains Source=hear.notifications,
DetailType=AlexaNotificationSourceReady, detail={schemaVersion:1,
eventId:"alexa-source:{notificationId}",notificationId}. The new source queue
requires the full EventBridge envelope. Do NOT route that source-only envelope
straight to the existing recipient delivery queue, which requires listenerId.

## Environment contract

Temporary shared-backend policy (explicitly requested by the project owner):
Development and production both use https://alexa.hear.media/api/v1 and
https://alexa.hear.media/api/v1/webhooks/event for now. The hear-py deployment
check accepts this shared hostname for both stages and continues to require
HTTPS. Do not change either stage to alexa.hear.surf without a separate request.

This is a public API/webhook endpoint exception, not a change to Go database,
private API, RabbitMQ, EventBridge, credentials or environment fencing. Requests
from both skill stages reach the shared backend. The new source pipeline remains
disabled: development source jobs still require verified backend/environment
routing before activation; do not bypass the source API's environment checks.

Go .env.dev and .env.production have the same configuration key contract, not
shared secrets or data. DATABASE_URL, CATALOG_DATABASE_URL, Redis, Meilisearch,
Docker backend network and HEAR_ENVIRONMENT must match the selected deployment.
Rabbit source queues carry explicit dev/prod names even on a shared broker.
The private Go API aliases are hear-alexa-source-dev and hear-alexa-source-prod.

Backend ALEXA_SOURCE_PLANNER_KEY must equal that environment's Go
ALEXA_SOURCE_API_KEY. It must differ between environments. Backend
ALEXA_SOURCE_PLANNER_ENVIRONMENT must match HEAR_ENVIRONMENT. This key is unrelated
to the Alexa webhook key. Do not store any real key in version control or chat.

Run script/check-env-contract.py --actual <Go-env-file> --environment
<development|production> --peer <other-Go-env-file> before deployment.
The examples and actual files must contain all referenced keys. The checker
prints key names and status only, not secrets or rendered connection strings.

Source preparation and dispatch have separate gates. ALEXA_SOURCE_ENABLED=true
runs Go preparation and the private audience API. ALEXA_EVENTBRIDGE_ENABLED=false
keeps new sources available to the inbox, projects their Redis indexes and retains
unpublished work in durable outboxes without exhausting retry attempts. Enable
EventBridge dispatch only after its AWS resources and runtime identity are verified.

## Required AWS configuration

Use outputs from the matching hear-py SAM stack, never guessed ARNs:
- NotificationEventBusArn -> ALEXA_EVENT_BUS_ARN
- NotificationSourceRuleName -> ALEXA_EVENTBRIDGE_RULE
- NotificationSourceQueueArn -> ALEXA_EVENTBRIDGE_TARGET_ARN
- Actual stack region -> AWS_REGION

An existing environment-specific bus can be selected using the SAM
NotificationEventBusName parameter. Otherwise SAM creates hear-notifications-dev
or hear-notifications-prod. Bus and target resource names must contain that
stage token. Go checks account/region, the live rule and its target before sends.
Use the returned GoSourceEventBridgePolicyArn with an approved AWS principal.
The Go principal needs EventBridge only; it does not need recipient SQS,
Amazon proactive client credentials, or access to the opposite environment.
Provide short-lived credentials through the AWS SDK credential chain where
possible. Environment credentials must be securely rotated; an expiring session
token needs an actual refreshing provider or a coordinated worker restart.

## Deployment sequence (do not skip steps)

1. Keep ALEXA_SOURCE_ENABLED=false and source relay/worker/API replicas zero.
   Keep SAM NotificationSourceEnabled=false. Audit existing EventBridge rules
   before changing routing: only one active source-processing path is allowed.
   The old /alexa/notification-source/ready callback is retired by this change.
   Disable or migrate any rule/API destination that still calls it.
2. Review database heads and backups separately for development and production.
   Deploy the backend migration chain through 0180_go_alexa_source_ownership.
   Its runtime ownership row starts disabled. Do not stamp or skip older
   migrations. Development was behind production when this migration was written.
3. Deploy the updated backend and verify all old Python Alexa source sweep,
   fanout and dispatch workers have drained/stopped. Other workers, listener
   webhooks and Firebase remain available. Existing source rows/read APIs remain.
4. Ordinary skill deployments keep NotificationSourceProvisioned=false until
   AWS source infrastructure access is granted. The GitHub variable is
   ALEXA_SOURCE_INFRASTRUCTURE_ENABLED_DEV or _PROD. This leaves the existing
   skill, outbound and recipient Lambda deployments independent of EventBridge.
   To create source resources, set NotificationSourceProvisioned=true while
   keeping NotificationSourceEnabled=false. Once provisioned, keep provisioning
   true to retain queues and policies; pause delivery with NotificationSourceEnabled.
   The deployment guard rejects accidental removal of existing source resources.
   Verify the
   source rule, source queue policy, SQS mapping, new source Lambda and existing
   recipient Lambda. Set the real Go bus/rule/target configuration and credentials.
5. Set the singleton runtime row to owner=go and environment=development or
   production in that database only. Start the Go source API first with
   ALEXA_SOURCE_ENABLED=true, ALEXA_EVENTBRIDGE_ENABLED=false and API replicas=1.
   Start the relay and worker together after the old source workers have stopped;
   inbox source preparation remains available while AWS setup is pending.
   Verify the authenticated public bridge returns a valid bounded candidate page.
   Startup rejects missing/mismatched ownership rather than claiming live jobs.
6. Enable SAM NotificationSourceEnabled in that environment and verify the rule
   and source SQS mapping are enabled. Set ALEXA_EVENTBRIDGE_ENABLED=true and
   restart the worker after validating its AWS identity. Run relay and worker with
   their bounded configured concurrency. Never run old Python source consumers
   alongside Go. Prefer one relay and a small worker count until measured.
7. Run a controlled end-to-end test using an authorised opted-in test listener
   and a new test release. Verify exact catalog revision -> source row ->
   RabbitMQ -> EventBridge acceptance -> source-page receipt -> recipient queue
   -> Amazon result -> backend delivery status. Test edits/deletes and retries.
8. Repeat the verified sequence for production with production-only resources.
   Promote identical reviewed code, not copied development credentials or data.

## Eligibility and recovery

Follow rank: exact source 100, related creator 90; meaningful prior listening
rank 30. Publication follows do not establish source eligibility. Prior listening
has no recency expiry and requires actual time_spent_ms >= min(30000, max(1,
track_duration_ms // 4)); unknown duration requires 30000 ms. Active listeners need valid
notification opt-in for external delivery; listening alone is not permission.
Do not force existing listeners' notifications_enabled values to true.
Recover legitimate lost preference events only after validation and deduplication.
The existing recipient pre-send validation rechecks heard, duplicate and opt-out
state. Follower-first candidate ordering is not a guarantee of strict global
completion order from a standard SQS queue.

Publication/recording revisions retain existing revision-one hash semantics.
Audio replacements change the logical revision. Only a release's obsolete source
is removed, not all pending releases from the same creator. Source cleanup uses
specific Redis indexes; heard keys expire rather than requiring a global scan.

PostgreSQL source outboxes are durable work/retry authority; RabbitMQ carries
bounded wakeups with manual acknowledgements and publisher confirms. Generation
and lease comparisons fence newer edits from stale workers. Expired leases are
reclaimed. Terminal errors retain a failed database row and a Rabbit DLQ record.
A failed row must be investigated and deliberately restaged; merely replaying
a stale Rabbit lease message does not reset its terminal database state.

EventBridge acceptance is not final notification delivery. Logs/metrics
hear_alexa_sources_prepared_total, hear_alexa_eventbridge_accepted_total and
hear_alexa_source_retries_total distinguish stages. The AWS source DLQ alarm
also catches source-planning failures; alarm actions must be attached to the
operations notification channel before alerts reach a person.

Delivery is at least once. Stable source event IDs, conditional Dynamo page
receipts and the existing per-recipient Amazon reference IDs limit duplicates.
Do not claim exactly-once external delivery. A delete immediately after the final
pre-send check can race with an accepted AWS event; Lambda must revalidate current
source state. Never bulk-redrive historical DLQs without classifying invalid,
expired and already-processed events first.

## Rollback

Stop source dispatch first: disable the EventBridge source rule/mapping and Go
relay/worker roles; preserve queued messages and durable rows. Do not delete
queues, purge receipts or turn on a second publisher to make queues look empty.
Keep schemas compatible while investigating. Re-enable any older pipeline only
as an explicit exclusive-owner rollback after reconciling its source IDs.

## Verification boundary

Local integration uses disposable PostgreSQL, Redis and RabbitMQ, not production
data. AWS SDK responses are mocked in tests. CI adds race detection and the same
isolated integrations. CPU improvements and delivery capacity require deployment
measurement; no million-listener throughput claim is made by this migration.
