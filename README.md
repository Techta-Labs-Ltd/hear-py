# Hear

Python Alexa skill backend deployed to AWS Lambda as a container image.

## Structure

- `main.py` — Lambda transport adapter
- `src/application.py` — application composition
- `src/handlers/registry.py` — ordered Alexa handler registration
- `src/middleware/` — request gates and interceptors
- `src/handlers/` — Alexa request and AudioPlayer handlers
- `src/services/api/` — Hear catalog and listener API integration
- `src/services/resolver_client.py` — typed external resolver API client
- `src/services/storage/` and `src/adapters/` — persistence
- `src/runtime/` — async Alexa dispatch runtime
- `template.yaml` — Alexa Lambda deployment

Search utterances are resolved by `POST https://resolver.hear.media/resolve`.
Canonical resolver entities are converted into Hear search filters before the
Alexa skill calls the catalog API. This repository does not host a resolver,
taxonomy runtime, inbound webhooks, notification ingestion, or outbound event
delivery.

## Configuration

Copy `.env.example` to `.env` for local development. The external resolver uses
the existing `HEAR_API_KEY`; it does not require separate resolver settings.

Production persistence uses DynamoDB when `HEAR_DDB_TABLE` is set. Memory
persistence is intended for local development only.

## Local checks

```sh
python .agents/skills/hear-alexa-python/scripts/audit_project.py .
python -m compileall -q main.py src config
python -m pytest -q
```
