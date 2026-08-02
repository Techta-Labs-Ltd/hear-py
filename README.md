# Hear

Alexa skill and webhook service deployed to AWS Lambda as a container image.

## Structure

- `main.py` — thin Lambda transport adapter
- `src/application.py` — application factory and persistence wiring
- `src/handlers/registry.py` — ordered request-handler registration
- `src/middleware/` — request gates and global interceptors
- `src/handlers/` — Alexa request handlers grouped by feature
- `src/services/api/` — Hear HTTP API integration
- `src/services/alexa/` — Alexa APIs, reminders, and device location
- `src/services/feedback/` — feedback interaction workflows
- `src/services/playback/` — playback lifecycle, sessions, and events
- `src/services/queue/` — queue advancement and refill workflows
- `src/services/storage/` — user persistence and playback-state repositories
- `src/services/` root modules — cross-feature workflows and observability
- `src/utils/` — pure parsing, normalization, formatting, and calculations
- `src/webhooks/` — separately deployed HTTP Lambda and webhook routing
- `src/runtime/` — async Alexa dispatch runtime
- `src/resolver/` — in-process taxonomy, temporal, context, fuzzy, and payload resolver
- `deploy/` and `template.yaml` — deployment policies and infrastructure

Handler and middleware order is behaviorally significant. Add handlers through
the registries instead of registering them in the Lambda entry point.

Search utterances are resolved locally in Lambda. The resolver separates exact
taxonomy facets from residual full-text terms, emits the structured Hear search
contract, and preserves that contract through browse pagination and queue refill.
The deployed `/webhook/taxonomy` endpoint queues background runtime refreshes.
A worker validates and stores an immutable snapshot, warms a candidate resolver
Lambda version using the existing image, and atomically promotes its alias.
Alexa requests never fetch the CDN manifest. Bundled `src/data/locations.json`
remains the static location source.

## Local checks

```sh
python -m pytest -q
python -m compileall -q main.py src config
python .agents/skills/hear-alexa-python/scripts/audit_project.py .
```

## Deployment permissions

The GitHub OIDC deployment role must be able to manage the stack's Lambda,
API Gateway, SQS, log, and generated IAM resources. Its DynamoDB scope must
include `hear-notification-inbox-*`, `hear-taxonomy-revision-*`, and
`hear-webhook-replay-*`. Its S3 scope must include both the bucket and objects
under `hear-taxonomy-snapshots-*`. These permissions are needed only when
CloudFormation creates or updates infrastructure. Runtime taxonomy refreshes
use the deployed webhook, queue, and Lambda resources and do not invoke
GitHub Actions or rebuild the container.

Copy `.env.example` to `.env` for local configuration. Production persistence
uses DynamoDB when `HEAR_DDB_TABLE` is set; memory persistence is intended for
local development only.

See [Outbound listening and feedback events](docs/outbound-listening-events.md)
for the playback/feedback webhook contract and AWS delivery checks.

See [Backend creator notification integration](docs/backend-notifications.md)
for follow/subscription events and the new track/publication notification
webhook contract.

See [Alexa listener identity and backend authentication](docs/backend-identity.md)
for non-empty Alexa identity handling, atomic listener upserts, and automatic
reconnection using the listener's permission-sourced email.

See [Runtime taxonomy revisions and zero-downtime activation](docs/runtime-taxonomy.md)
for the backend taxonomy webhook, default DynamoDB revision, immutable resolver
build, and alias-promotion contract.
