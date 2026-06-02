#!/usr/bin/env bash
# Build the production Docker image and push to the environment's ECR repository.
#
# Usage:
#   ./deploy/ecr-push.sh <environment> <image-tag>
#
# Prerequisites:
#   - AWS CLI v2 configured (or role assumed via CI)
#   - Docker daemon running
#   - ECR repository named  uscheduler-<environment>  must exist
#
# Example:
#   ./deploy/ecr-push.sh staging v1.4.2

set -euo pipefail

ENVIRONMENT=${1:?"Usage: ecr-push.sh <environment> <image-tag>"}
IMAGE_TAG=${2:?"Usage: ecr-push.sh <environment> <image-tag>"}

AWS_REGION=${AWS_REGION:-us-east-1}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/uscheduler-${ENVIRONMENT}"

echo "==> Logging in to ECR (${AWS_REGION})"
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "==> Building production image"
docker build \
  --target runtime \
  --tag "${ECR_REPO}:${IMAGE_TAG}" \
  --tag "${ECR_REPO}:latest" \
  ./backend

echo "==> Pushing ${ECR_REPO}:${IMAGE_TAG}"
docker push "${ECR_REPO}:${IMAGE_TAG}"
docker push "${ECR_REPO}:latest"

echo "==> Done: ${ECR_REPO}:${IMAGE_TAG}"
