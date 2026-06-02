#!/usr/bin/env bash
# Register a new ECS task definition revision (with the updated image) and
# update the ECS service to roll out the new revision.
#
# Usage:
#   ./deploy/ecs-deploy.sh <environment> <image-tag>
#
# Naming conventions expected in AWS:
#   ECS cluster:  uscheduler-<environment>
#   ECS service:  uscheduler-api-<environment>
#   Task family:  uscheduler-api-<environment>
#   ECR repo:     <account>.dkr.ecr.<region>.amazonaws.com/uscheduler-<environment>
#
# The script fetches the CURRENT task definition, replaces the container image,
# registers the new revision, and updates the service — zero changes to other
# task definition fields (CPU, memory, env vars, secrets, log config, etc.).
#
# Example:
#   ./deploy/ecs-deploy.sh staging v1.4.2

set -euo pipefail

ENVIRONMENT=${1:?"Usage: ecs-deploy.sh <environment> <image-tag>"}
IMAGE_TAG=${2:?"Usage: ecs-deploy.sh <environment> <image-tag>"}

AWS_REGION=${AWS_REGION:-us-east-1}
CLUSTER="uscheduler-${ENVIRONMENT}"
SERVICE="uscheduler-api-${ENVIRONMENT}"
TASK_FAMILY="uscheduler-api-${ENVIRONMENT}"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
NEW_IMAGE="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/uscheduler-${ENVIRONMENT}:${IMAGE_TAG}"

echo "==> Fetching current task definition for ${TASK_FAMILY}"
CURRENT=$(aws ecs describe-task-definition \
  --task-definition "${TASK_FAMILY}" \
  --region "${AWS_REGION}" \
  --query taskDefinition)

echo "==> Preparing new revision with image: ${NEW_IMAGE}"
NEW_TASK_DEF=$(echo "${CURRENT}" | jq --arg image "${NEW_IMAGE}" '
  .containerDefinitions[0].image = $image
  | del(.taskDefinitionArn, .revision, .status,
        .requiresAttributes, .compatibilities,
        .registeredAt, .registeredBy)
')

echo "==> Registering new task definition revision"
NEW_TASK_ARN=$(aws ecs register-task-definition \
  --cli-input-json "${NEW_TASK_DEF}" \
  --region "${AWS_REGION}" \
  --query "taskDefinition.taskDefinitionArn" \
  --output text)

echo "==> Registered: ${NEW_TASK_ARN}"

echo "==> Updating ECS service ${SERVICE} in cluster ${CLUSTER}"
aws ecs update-service \
  --cluster "${CLUSTER}" \
  --service "${SERVICE}" \
  --task-definition "${NEW_TASK_ARN}" \
  --region "${AWS_REGION}" \
  --force-new-deployment \
  --output text --query "service.serviceName"

echo "==> Waiting for deployment to stabilise (timeout: 10 min)"
aws ecs wait services-stable \
  --cluster "${CLUSTER}" \
  --services "${SERVICE}" \
  --region "${AWS_REGION}"

echo "==> Deployment complete: ${SERVICE} → ${NEW_TASK_ARN}"
