#!/usr/bin/env bash
# ONE-TIME setup: creates the GitHub Actions OIDC identity provider and the
# deploy role that the workflow assumes. Requires IAM admin permissions.
# After it runs, add the printed ARN as a GitHub repo secret named
# AWS_DEPLOY_ROLE_ARN.
set -euo pipefail

ACCOUNT=650790810013
ROLE_NAME=github-actions-hear-deploy
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PROVIDER_ARN="arn:aws:iam::${ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"

# 1) GitHub OIDC identity provider (idempotent)
if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN" >/dev/null 2>&1; then
  echo "OIDC provider already exists"
else
  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 >/dev/null
  echo "created GitHub OIDC provider"
fi

# 2) Deploy role + trust policy
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam update-assume-role-policy --role-name "$ROLE_NAME" \
    --policy-document "file://$HERE/deploy/oidc-trust-policy.json" >/dev/null
  echo "updated trust policy on $ROLE_NAME"
else
  aws iam create-role --role-name "$ROLE_NAME" \
    --description "GitHub Actions deploy role for Techta-Labs-Ltd/hear-py" \
    --assume-role-policy-document "file://$HERE/deploy/oidc-trust-policy.json" >/dev/null
  echo "created role $ROLE_NAME"
fi

# 3) Permissions
aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name hear-deploy \
  --policy-document "file://$HERE/deploy/oidc-permissions-policy.json"
echo "attached permissions policy"

echo
echo "=================================================================="
echo "Add this as a GitHub repo secret named  AWS_DEPLOY_ROLE_ARN :"
echo "  arn:aws:iam::${ACCOUNT}:role/${ROLE_NAME}"
echo "=================================================================="
