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
- `src/webhooks/` — HTTP normalization, routing, and webhook endpoints
- `src/runtime/` — async Alexa dispatch runtime
- `src/resolver/` — in-process taxonomy, temporal, context, fuzzy, and payload resolver
- `deploy/` and `template.yaml` — deployment policies and infrastructure

Handler and middleware order is behaviorally significant. Add handlers through
the registries instead of registering them in the Lambda entry point.

Search utterances are resolved locally in Lambda. The resolver separates exact
taxonomy facets from residual full-text terms, emits the structured Hear search
contract, and preserves that contract through browse pagination and queue refill.
The `/webhook/taxonomy` endpoint records new taxonomy revisions; Lambda workers
hash-check changed files, cache them under `/tmp`, and atomically swap a valid
snapshot. Bundled `src/data/locations.json` remains the static location source.

## Local checks

```sh
python -m pytest -q
python -m compileall -q main.py src config
python .agents/skills/hear-alexa-python/scripts/audit_project.py .
```

Copy `.env.example` to `.env` for local configuration. Production persistence
uses DynamoDB when `HEAR_DDB_TABLE` is set; memory persistence is intended for
local development only.
