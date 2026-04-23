#!/usr/bin/env bash
# Build, push, and update the portal worker Lambda (Step 3g).
#
# Idempotent — re-run after every code or dep change. First run also
# creates the ECR repo, Lambda function, EventBridge rule, and IAM
# permission. See README.md for the prerequisites.

set -euo pipefail

# ── Config ────────────────────────────────────────────
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
ECR_REPO="${ECR_REPO:-barkain-portal-worker}"
LAMBDA_NAME="${LAMBDA_NAME:-barkain-portal-worker}"
LAMBDA_ROLE_ARN="${LAMBDA_ROLE_ARN:?Set LAMBDA_ROLE_ARN to the IAM role ARN — see README.md §IAM}"
SECRETS_ARN="${SECRETS_ARN:?Set SECRETS_ARN to the Secrets Manager ARN holding DATABASE_URL etc.}"
EVENT_RULE_NAME="${EVENT_RULE_NAME:-barkain-portal-cron}"
EVENT_SCHEDULE="${EVENT_SCHEDULE:-cron(0 */6 * * ? *)}"

# ── Resolve ECR URI ───────────────────────────────────
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"

# ── Step 1: ensure repo exists ────────────────────────
if ! aws ecr describe-repositories --region "$AWS_REGION" --repository-names "$ECR_REPO" >/dev/null 2>&1; then
  echo "Creating ECR repo $ECR_REPO …"
  aws ecr create-repository --region "$AWS_REGION" --repository-name "$ECR_REPO" >/dev/null
fi

# ── Step 2: docker build + push ───────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_URI"

echo "Building image …"
docker build \
  --platform linux/amd64 \
  -t "${ECR_REPO}:latest" \
  -f "$SCRIPT_DIR/Dockerfile" \
  "$REPO_ROOT"

echo "Pushing to ECR …"
docker tag "${ECR_REPO}:latest" "${ECR_URI}:latest"
docker push "${ECR_URI}:latest"

IMAGE_DIGEST="$(aws ecr describe-images --region "$AWS_REGION" --repository-name "$ECR_REPO" \
  --image-ids imageTag=latest --query 'imageDetails[0].imageDigest' --output text)"
IMAGE_URI="${ECR_URI}@${IMAGE_DIGEST}"

# ── Step 3: create or update Lambda ───────────────────
if aws lambda get-function --function-name "$LAMBDA_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
  echo "Updating Lambda function code …"
  aws lambda update-function-code \
    --region "$AWS_REGION" \
    --function-name "$LAMBDA_NAME" \
    --image-uri "$IMAGE_URI" >/dev/null
else
  echo "Creating Lambda function …"
  aws lambda create-function \
    --region "$AWS_REGION" \
    --function-name "$LAMBDA_NAME" \
    --package-type Image \
    --code "ImageUri=$IMAGE_URI" \
    --role "$LAMBDA_ROLE_ARN" \
    --timeout 300 \
    --memory-size 512 \
    --environment "Variables={SECRETS_ARN=$SECRETS_ARN}" >/dev/null
fi

# ── Step 4: ensure EventBridge cron rule + target ─────
if ! aws events describe-rule --name "$EVENT_RULE_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
  echo "Creating EventBridge rule $EVENT_RULE_NAME …"
  aws events put-rule \
    --region "$AWS_REGION" \
    --name "$EVENT_RULE_NAME" \
    --schedule-expression "$EVENT_SCHEDULE" >/dev/null
fi

LAMBDA_ARN="arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:${LAMBDA_NAME}"
RULE_ARN="arn:aws:events:${AWS_REGION}:${AWS_ACCOUNT_ID}:rule/${EVENT_RULE_NAME}"

aws events put-targets \
  --region "$AWS_REGION" \
  --rule "$EVENT_RULE_NAME" \
  --targets "Id=1,Arn=${LAMBDA_ARN}" >/dev/null

aws lambda add-permission \
  --region "$AWS_REGION" \
  --function-name "$LAMBDA_NAME" \
  --statement-id "${EVENT_RULE_NAME}-invoke" \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "$RULE_ARN" 2>/dev/null || true  # idempotent — ignore "already exists"

echo "Deployed $LAMBDA_NAME (image $IMAGE_URI)"
echo "Test invoke: aws lambda invoke --function-name $LAMBDA_NAME --invocation-type Event /tmp/out.json"
