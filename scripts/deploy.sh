#!/usr/bin/env bash
# One-shot manual deploy of the Hear Python skill as a Lambda container image.
# Creates the function on first run, updates it thereafter. Role + env vars are
# copied from the existing `Hear` function, so no secrets live in this script.
#
# Usage:  scripts/deploy.sh [image-tag]
set -euo pipefail

ACCOUNT=692859951746
REGION=eu-west-1
ECR_REPO=hear-python
FUNCTION=Hear-Python-dev
SOURCE_FUNCTION=Hear          # copy role + env from this existing function
TAG="${1:-latest}"

REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
IMAGE="$REGISTRY/$ECR_REPO:$TAG"

echo ">> ensuring ECR repo '$ECR_REPO' exists"
aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$ECR_REPO" --region "$REGION" >/dev/null

echo ">> logging in to ECR"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

echo ">> building + pushing image: $IMAGE"
docker build --platform linux/amd64 --provenance=false -t "$IMAGE" .
docker push "$IMAGE"

ROLE=$(aws lambda get-function-configuration --function-name "$SOURCE_FUNCTION" --region "$REGION" --query 'Role' --output text 2>/dev/null)
ENVJSON=$(aws lambda get-function-configuration --function-name "$SOURCE_FUNCTION" --region "$REGION" --query 'Environment' --output json 2>/dev/null)
if [ -z "${ROLE:-}" ]; then
  echo ">> source function '$SOURCE_FUNCTION' not found; copying role+env from '$FUNCTION'"
  ROLE=$(aws lambda get-function-configuration --function-name "$FUNCTION" --region "$REGION" --query 'Role' --output text)
  ENVJSON=$(aws lambda get-function-configuration --function-name "$FUNCTION" --region "$REGION" --query 'Environment' --output json)
fi

if aws lambda get-function --function-name "$FUNCTION" --region "$REGION" >/dev/null 2>&1; then
  echo ">> updating existing function code: $FUNCTION"
  aws lambda update-function-code --function-name "$FUNCTION" --image-uri "$IMAGE" --region "$REGION" >/dev/null
else
  echo ">> creating function: $FUNCTION"
  aws lambda create-function --function-name "$FUNCTION" \
    --package-type Image --code ImageUri="$IMAGE" \
    --role "$ROLE" --environment "$ENVJSON" \
    --timeout 30 --memory-size 1024 --architectures x86_64 \
    --region "$REGION" >/dev/null
fi

aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"
echo ">> done: $FUNCTION now running $IMAGE"
