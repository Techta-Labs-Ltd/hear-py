# Hear

Python Alexa skill backend deployed to AWS Lambda as a container image.

## Structure

- `main.py` - Lambda transport adapter
- `src/application.py` - application composition
- `src/registry.py` - ordered Alexa controller registration
- `src/middleware/` - ordered gates and interceptors
- `src/controllers/` - Alexa request and AudioPlayer controllers
- `src/models/` - class-owned feature workflows and state transitions
- `src/models/user.py` - central request state and persistence key model
- `src/clients/` and `src/services/` - external integrations
- `src/database/` - DynamoDB and persistence middleware
- `src/constants/` and `src/utils/` - focused values, filters, and deadline helpers
- `src/alexa/runtime.py` - async Alexa dispatch runtime
- `template.yaml` - Alexa Lambda, DynamoDB, and outbound SQS deployment

Search utterances are resolved by `POST https://resolver.hear.media/resolve`.
Canonical resolver entities are converted into Hear search filters before the
Alexa skill calls the catalog API. Playback, feedback, follow, unfollow, and
report events are published to SQS and forwarded by the outbound worker to the
Hear backend. This repository does not host a resolver, taxonomy runtime,
inbound webhooks, or notification ingestion.

## Configuration

Copy `.env.example` to `.env` for local development. The external resolver uses
the existing `HEAR_API_KEY`. Runtime configuration is owned by `Settings`; code
under `src` does not read environment variables directly.

The `.env` flags are grouped by responsibility:

- `HEAR_API_*` configures the Hear API endpoint, authentication, retries, and backoff.
- `HEAR_RESOLVER_*` configures the resolver endpoint, timeout, country, and timezone.
- `HEAR_HTTP_*`, `HEAR_ALEXA_API_TIMEOUT_MS`, and `HEAR_PROGRESSIVE_*` configure outbound HTTP behavior.
- `HEAR_DDB_*` and `HEAR_PERSISTENCE_*` configure durable User persistence.
- `SQS_OUT_QUEUE_URL`, `WEBHOOK_OUTBOUND_*`, and `HEAR_EVENT_WEBHOOK_TIMEOUT_MS` configure backend event delivery.
- `HEAR_FEEDBACK_*`, `HEAR_PLAYBACK_*`, `HEAR_SEEK_STEP_MS`, queue, browse, search, and history flags configure application behavior.
- `SENTRY_*`, `STAGE`, `NODE_ENV`, and `POWERTOOLS_*` configure runtime diagnostics.

Use `.env.example` as the complete non-secret configuration contract. Keep real
API keys and DSNs only in `.env` locally or encrypted SSM parameters in AWS.

The deployment stack creates and owns an encrypted DynamoDB table for durable
listener state, with point-in-time recovery, TTL, and retained deletion policy.
`HEAR_DDB_TABLE` selects the table outside the stack. Memory persistence is
intended for local development only.

The deployment stack also creates an encrypted outbound SQS queue, a dead-letter
queue, and a batch consumer. Publication feedback identifies the publication as
its subject and includes all listened content IDs. Content feedback identifies
one complete track as its subject.

## Local checks

```sh
python .agents/skills/hear-architecture-refactor/scripts/audit_architecture.py . --strict
python -m ruff check src tests
python -m compileall -q main.py src config
python -m pytest -q
```

## GitHub deployments

Two independent GitHub Actions workflows keep the release paths explicit:

- `deploy-develop.yml` tests pull requests to `develop` and deploys pushes from
  `develop` to the `development` GitHub environment.
- `deploy-main.yml` tests pull requests to `main` and deploys pushes from `main`
  to the `production` GitHub environment.

Each workflow can also be run manually, but only from its matching branch.

Create GitHub environments named `development` and `production` for deployment
protection. Add these distinctly named secrets and variables at repository or
environment scope; the workflows never reuse a configuration name across
stages:

| Type | Development name | Development value | Production name | Production value |
|---|---|---|---|---|
| Secret | `AWS_DEPLOY_ROLE_ARN_DEV` | development role ARN | `AWS_DEPLOY_ROLE_ARN_PROD` | production role ARN |
| Secret | SSM `/hear/development/HEAR_API_KEY` | development API key | `HEAR_API_KEY_PROD` | production API key |
| Secret | SSM `/hear/development/WEBHOOK_OUTBOUND_SECRET` | development webhook secret | `WEBHOOK_OUTBOUND_SECRET_PROD` | production webhook secret |
| Secret | SSM `/hear/development/SENTRY_DSN` | development Sentry DSN | `SENTRY_DSN_PROD` | production Sentry DSN |
| Variable | `STACK_NAME_DEV` | `hear-py-development` | `STACK_NAME_PROD` | `hear-py-prod` |
| Variable | `SHORT_STAGE_DEV` | `dev` | `SHORT_STAGE_PROD` | `prod` |
| Variable | `ALEXA_SKILL_ID_DEV` | development skill ID | `ALEXA_SKILL_ID_PROD` | production skill ID |
| Variable | `AWS_REGION_DEV` | `eu-west-1` | `AWS_REGION_PROD` | `eu-west-1` |
| Variable | `ECR_REPO_DEV` | `hear-python` | `ECR_REPO_PROD` | `hear-python` |
| Variable | `HEAR_API_URL_DEV` | development API URL | `HEAR_API_URL_PROD` | production API URL |
| Variable | `HEAR_API_PATH_PREFIX_DEV` | `alexa` | `HEAR_API_PATH_PREFIX_PROD` | `alexa` |
| Variable | `WEBHOOK_OUTBOUND_URL_DEV` | development event endpoint | `WEBHOOK_OUTBOUND_URL_PROD` | production event endpoint |
| Variable | `POWERTOOLS_LOG_LEVEL_DEV` | `DEBUG` | `POWERTOOLS_LOG_LEVEL_PROD` | `INFO` |
| Variable | `PROVISIONED_CONCURRENCY_DEV` | `0` | `PROVISIONED_CONCURRENCY_PROD` | `0` |
| Variable | `SSM_PARAMETER_PREFIX_DEV` | `/hear/development` | None | production secrets come from GitHub |

Development reads sensitive configuration from encrypted SSM parameters:

```text
/hear/development/HEAR_API_KEY
/hear/development/WEBHOOK_OUTBOUND_SECRET
/hear/development/SENTRY_DSN
```

Production reads `HEAR_API_KEY_PROD`, `WEBHOOK_OUTBOUND_SECRET_PROD`, and
`SENTRY_DSN_PROD` directly from the protected GitHub `production` environment
on every deployment. `HEAR_API_KEY_PROD` is required. The other two secrets are
optional; event signing falls back to the API key when the dedicated secret is
absent. Changing a GitHub secret takes effect on the next push to `main` or a
manual run of the production workflow. Configure required
reviewers and prevent self-review on the `production` GitHub environment for a
production approval gate. Run `scripts/setup-github-oidc.sh` once with IAM
administrator credentials to create or update the environment-scoped role.

## Live AWS Lambda testing

`samconfig.toml` contains independent `development` and `production` SAM
profiles. The live deployment helper builds the current checkout as a Linux
container, pushes it to ECR, deploys the selected stack, and invokes the real
Lambda resolver diagnostic.

Prerequisites are authenticated AWS CLI access, Docker, AWS SAM CLI, the Alexa
skill ID, and the environment's `HEAR_API_KEY` in SSM.

Deploy and test development:

```powershell
.\scripts\deploy-live.ps1 `
  -Environment development `
  -AlexaSkillId "amzn1.ask.skill.your-development-id"
```

Deploy and test production, with both an explicit production switch and SAM
change-set confirmation:

```powershell
.\scripts\deploy-live.ps1 `
  -Environment production `
  -AlexaSkillId "amzn1.ask.skill.your-production-id" `
  -ConfirmProduction
```

Pass `-AwsProfile profile-name` when not using the AWS CLI's default profile.
The TOML contains no secrets; the helper reads `/hear/<environment>/HEAR_API_KEY`
and the optional `SENTRY_DSN` from encrypted SSM parameters.
