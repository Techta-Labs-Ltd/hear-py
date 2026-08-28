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

The deployment stack creates and owns an encrypted DynamoDB table for durable
listener state, with point-in-time recovery, TTL, and retained deletion policy.
`HEAR_DDB_TABLE` selects the table outside the stack. Memory persistence is
intended for local development only.

## Local checks

```sh
python .agents/skills/hear-alexa-python/scripts/audit_project.py .
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
| Variable | `STACK_NAME_DEV` | `hear-py-development` | `STACK_NAME_PROD` | `hear-py-production` |
| Variable | `SHORT_STAGE_DEV` | `dev` | `SHORT_STAGE_PROD` | `prod` |
| Variable | `ALEXA_SKILL_ID_DEV` | development skill ID | `ALEXA_SKILL_ID_PROD` | production skill ID |
| Variable | `AWS_REGION_DEV` | `eu-west-1` | `AWS_REGION_PROD` | `eu-west-1` |
| Variable | `ECR_REPO_DEV` | `hear-python` | `ECR_REPO_PROD` | `hear-python` |
| Variable | `HEAR_API_URL_DEV` | development API URL | `HEAR_API_URL_PROD` | production API URL |
| Variable | `HEAR_API_PATH_PREFIX_DEV` | `alexa` | `HEAR_API_PATH_PREFIX_PROD` | `alexa` |
| Variable | `POWERTOOLS_LOG_LEVEL_DEV` | `DEBUG` | `POWERTOOLS_LOG_LEVEL_PROD` | `INFO` |
| Variable | `SSM_PARAMETER_PREFIX_DEV` | `/hear/development` | `SSM_PARAMETER_PREFIX_PROD` | `/hear/production` |

Store sensitive application configuration in encrypted SSM parameters beneath
each environment's prefix:

```text
/hear/development/HEAR_API_KEY
/hear/development/SENTRY_DSN
/hear/production/HEAR_API_KEY
/hear/production/SENTRY_DSN
```

`HEAR_API_KEY` is required and `SENTRY_DSN` is optional. Configure required
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
