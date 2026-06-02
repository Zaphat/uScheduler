# uScheduler — Dealership Appointment Scheduler

A production-grade REST API for conflict-free automotive service appointment scheduling.  
Enforces resource constraints (service bay + technician) with a distributed-lock + DB-transaction double-booking defence.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Environments](#environments)
3. [Local Development](#local-development)
4. [Secrets Management](#secrets-management)
5. [CI/CD Pipeline](#cicd-pipeline)
6. [Deployment](#deployment)
7. [Running Tests](#running-tests)
8. [Seed Data & cURL Examples](#seed-data--curl-examples)
9. [API Overview](#api-overview)
10. [Project Structure](#project-structure)

---

## Architecture

```
Client
  └── FastAPI (uvicorn, 2 workers)
        ├── Auth          JWT (python-jose) + bcrypt
        ├── Service layer Booking orchestration, operating-hours guard
        ├── Lock layer    Redis distributed lock (SET NX + Lua CAS release)
        ├── Repository    SQLAlchemy 2 async (asyncpg)
        └── DB            PostgreSQL 16
```

**Double-booking defence (3 layers)**

1. Redis distributed lock per `(bay, 15-min bucket)` and `(technician, 15-min bucket)` — first concurrent request wins.
2. DB-level conflict re-check inside the transaction — defence-in-depth.
3. PostgreSQL overlap constraint on the `appointments` table.

**Infrastructure (AWS)**

```
Internet → ALB → ECS Fargate (uscheduler-api) → Aurora PostgreSQL + ElastiCache Redis
                                                ↓
                                       Secrets Manager (secrets at runtime)
                                                ↓
                                       CloudWatch Logs + Prometheus /metrics
```

---

## Environments

| Name      | Trigger                          | Secrets source         | Approval |
|-----------|----------------------------------|------------------------|----------|
| `local`   | `docker compose up`              | docker-compose env vars | —        |
| `dev`     | Push to `main`                   | AWS Secrets Manager    | Auto     |
| `staging` | Git tag `v*.*.*`                 | AWS Secrets Manager    | Auto     |
| `prod`    | Git tag `v*.*.*` (after staging) | AWS Secrets Manager    | Manual|

The `ENVIRONMENT` environment variable drives the behaviour:
- `local` → no AWS call; values come directly from the process environment.
- anything else → `config.py` calls `secretsmanager:GetSecretValue` on startup for `uscheduler/{ENVIRONMENT}/app` and injects the JSON values into `os.environ` before Pydantic reads them.

---

## Local Development

**Prerequisites:** Docker Desktop

```bash
cd backend
docker compose up --build
```

The container automatically runs migrations and seeds demo data on first start.  
On subsequent restarts the seed step is skipped.

API: http://localhost:8000  
Docs: http://localhost:8000/docs

No `.env` file needed. All values are declared inline in `docker-compose.yml` — they are dev-only, non-sensitive defaults safe to commit.

**Run without Docker (Python 3.12+ required)**

```bash
cd backend
pip install -e ".[dev]"

export ENVIRONMENT=local
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/uscheduler
export REDIS_URL=redis://localhost:6379/0
export SECRET_KEY=local-dev-only-secret-key-not-used-in-any-real-env

alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

---

## Secrets Management

Secrets **never** live in the repository or on disk.  
In non-local environments the application calls AWS Secrets Manager at startup.

### Secret structure

One JSON secret per environment, at path `uscheduler/{environment}/app`:

```json
{
  "DATABASE_URL":                "postgresql+asyncpg://user:pass@host/db",
  "REDIS_URL":                   "redis://host:6379/0",
  "SECRET_KEY":                  "<32+ byte random hex>",
  "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
  "ALLOWED_ORIGINS":             "[\"https://app.example.com\"]"
}
```

Create the secret (run once per environment):

```bash
aws secretsmanager create-secret \
  --name "uscheduler/dev/app" \
  --region us-east-1 \
  --secret-string '{
    "DATABASE_URL": "postgresql+asyncpg://...",
    "REDIS_URL": "redis://...",
    "SECRET_KEY": "'"$(openssl rand -hex 32)"'",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
    "ALLOWED_ORIGINS": "[\"https://dev.app.example.com\"]"
  }'
```

### Required IAM permissions

The ECS **task role** (`uscheduler-ecs-task-{environment}`) needs:

```json
{
  "Effect": "Allow",
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "arn:aws:iam::ACCOUNT:secret:uscheduler/ENVIRONMENT/app-*"
}
```

### Rotating secrets

Update the secret value in AWS Secrets Manager. The next ECS deployment (or container restart) picks up the new values automatically — no code change required.

---

## CI/CD Pipeline

### GitHub Actions

```
Every push / PR
  └── ci.yml
        ├── ruff lint
        ├── pytest (SQLite in-memory + fakeredis — no AWS needed)
        └── docker build --target runtime  (smoke-test the production image)

Push to main  →  deploy.yml  →  build & push ECR  →  ECS deploy (dev)   [auto]
Tag v*.*.*    →  deploy.yml  →  build & push ECR  →  ECS deploy (staging) [auto]
                                                   →  ECS deploy (prod)   [manual approval]
```

**One-time GitHub repo setup:**

1. Create GitHub Environments: `dev`, `staging`, `prod`.
2. On the `prod` environment add **Required reviewers**.
3. Add a variable `AWS_DEPLOY_ROLE_ARN` to each environment (the IAM role the workflow assumes via OIDC).
4. Configure the IAM OIDC trust policy in each AWS account to allow `token.actions.githubusercontent.com` for this repo.

### Jenkins

A `Jenkinsfile` at the repo root provides the equivalent pipeline for Jenkins users.

**One-time Jenkins setup:**

| Credential ID  | Type                 | Account       |
|----------------|----------------------|---------------|
| `aws-dev`      | AWS credentials      | dev account   |
| `aws-staging`  | AWS credentials      | staging account |
| `aws-prod`     | AWS credentials      | prod account  |

Create a Pipeline job pointing at this repository. Production deployments pause for a manual `input` approval.

---

## Deployment

### AWS infrastructure naming conventions

| Resource      | Name pattern                          |
|---------------|---------------------------------------|
| ECR repo      | `uscheduler-{environment}`            |
| ECS cluster   | `uscheduler-{environment}`            |
| ECS service   | `uscheduler-api-{environment}`        |
| ECS task      | `uscheduler-api-{environment}`        |
| SM secret     | `uscheduler/{environment}/app`        |
| CloudWatch LG | `/ecs/uscheduler-{environment}`       |

### First deployment to a new environment

```bash
# 1. Create the Secrets Manager secret (see above)

# 2. Create the ECR repository
aws ecr create-repository --repository-name uscheduler-dev --region us-east-1

# 3. Register the initial ECS task definition (edit the template first)
cp deploy/task-definition.template.json /tmp/td-dev.json
# edit: replace ACCOUNT_ID, REGION, ENVIRONMENT placeholders
aws ecs register-task-definition --cli-input-json file:///tmp/td-dev.json

# 4. Create the ECS cluster + service (via Terraform / CDK / console)

# 5. Run the first deployment
./deploy/ecr-push.sh dev $(git rev-parse HEAD)
./deploy/ecs-deploy.sh dev $(git rev-parse HEAD)
```

### Manual rollback

```bash
# Roll back to a previous image tag
./deploy/ecs-deploy.sh prod v1.3.9
```

---

## Running Tests


```bash
cd backend
pip install -e ".[dev]"
pytest tests/ -q
```

```bash
# With coverage
pytest tests/ --cov=app --cov-report=term-missing
```

---

## Seed Data & cURL Examples

After running `python -m scripts.seed` the database contains the following fixed-ID entities — copy-paste the IDs straight into the cURL commands below.

### Seeded entities

| Type | Name | ID |
|------|------|----|
| Dealership | Sunrise Auto Service | `d0000000-0000-0000-0000-000000000001` |
| Service Type | Oil Change (60 min) | `s0000000-0000-0000-0000-000000000001` |
| Service Type | Tyre Rotation (45 min) | `s0000000-0000-0000-0000-000000000002` |
| Service Type | Engine Overhaul (240 min) | `s0000000-0000-0000-0000-000000000003` |
| Customer | Jane Smith `jane@example.com` / `Password123` | `c0000000-0000-0000-0000-000000000001` |
| Customer | John Doe `john@example.com` / `Password123` | `c0000000-0000-0000-0000-000000000002` |
| Vehicle | 2021 Toyota Camry (Jane) | `v0000000-0000-0000-0000-000000000001` |
| Vehicle | 2020 Honda Civic (John) | `v0000000-0000-0000-0000-000000000002` |
| Appointment | Jane / Camry / Oil Change — 2026-06-20 13:00 UTC (09:00 EDT) | `a0000000-0000-0000-0000-000000000001` |
| Appointment | John / Civic / Tyre Rotation — 2026-06-20 14:00 UTC (10:00 EDT) | `a0000000-0000-0000-0000-000000000002` |
| Appointment | Jane / Camry / Engine Overhaul — 2026-06-20 17:00 UTC (13:00 EDT) | `a0000000-0000-0000-0000-000000000003` |

### cURL walkthrough

All requests target `http://localhost:8000/api/v1`. Run these in order — later steps reuse `$TOKEN` and `$APPT_ID` captured earlier.

#### 1. Health check

```bash
curl -s http://localhost:8000/health | jq
```

#### 2. Log in as Jane and capture the token

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@example.com","password":"Password123"}' \
  | jq -r '.access_token')
echo $TOKEN
```

#### 3. List dealerships

```bash
curl -s http://localhost:8000/api/v1/dealerships \
  -H "Authorization: Bearer $TOKEN" | jq
```

#### 4. List service types for the seeded dealership

```bash
curl -s "http://localhost:8000/api/v1/dealerships/d0000000-0000-0000-0000-000000000001/service-types" \
  -H "Authorization: Bearer $TOKEN" | jq
```

#### 5. Check available slots (Oil Change, 2026-06-21)

> The dealership is in `America/New_York` (EDT = UTC-4). Business hours are 08:00–18:00 local time.  
> Use UTC times offset by +4 h: 09:00 EDT = **13:00 UTC**, 18:00 EDT = **22:00 UTC**.

```bash
curl -s "http://localhost:8000/api/v1/availability\
?dealership_id=d0000000-0000-0000-0000-000000000001\
&service_type_id=s0000000-0000-0000-0000-000000000001\
&date=2026-06-21" \
  -H "Authorization: Bearer $TOKEN" | jq
```

#### 6. Book a new appointment

```bash
APPT_ID=$(curl -s -X POST http://localhost:8000/api/v1/appointments \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "vehicle_id":      "v0000000-0000-0000-0000-000000000001",
    "dealership_id":   "d0000000-0000-0000-0000-000000000001",
    "service_type_id": "s0000000-0000-0000-0000-000000000001",
    "scheduled_start": "2026-06-21T13:00:00Z"
  }' | jq -r '.id')
echo $APPT_ID
```

#### 7. Get a specific appointment

```bash
# New appointment booked above
curl -s "http://localhost:8000/api/v1/appointments/$APPT_ID" \
  -H "Authorization: Bearer $TOKEN" | jq

# Pre-seeded appointment (no booking required)
curl -s "http://localhost:8000/api/v1/appointments/a0000000-0000-0000-0000-000000000001" \
  -H "Authorization: Bearer $TOKEN" | jq
```

#### 8. List Jane's appointments

```bash
curl -s "http://localhost:8000/api/v1/appointments?page=1&limit=20" \
  -H "Authorization: Bearer $TOKEN" | jq
```

#### 9. Cancel an appointment

```bash
curl -s -X PATCH "http://localhost:8000/api/v1/appointments/$APPT_ID/cancel" \
  -H "Authorization: Bearer $TOKEN" | jq
```

#### 10. Register a new customer

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Alice Brown","email":"alice@example.com","password":"Password123"}' | jq
```

> The full extended example file is at [backend/docs/curl-examples.md](./backend/docs/curl-examples.md).  
> Interactive Swagger UI: **http://localhost:8000/docs**

---

## API Overview

| Method  | Path                                          | Auth | Description                          |
|---------|-----------------------------------------------|------|--------------------------------------|
| `POST`  | `/api/v1/auth/register`                       | —    | Register a new customer              |
| `POST`  | `/api/v1/auth/login`                          | —    | Obtain JWT bearer token              |
| `GET`   | `/api/v1/availability`                        | JWT  | List open slots for a date           |
| `POST`  | `/api/v1/appointments`                        | JWT  | Book an appointment                  |
| `GET`   | `/api/v1/appointments`                        | JWT  | List my appointments (paginated)     |
| `GET`   | `/api/v1/appointments/{id}`                   | JWT  | Get appointment detail               |
| `PATCH` | `/api/v1/appointments/{id}/cancel`            | JWT  | Cancel a confirmed appointment       |
| `GET`   | `/api/v1/dealerships`                         | JWT  | List dealerships                     |
| `GET`   | `/api/v1/dealerships/{id}/service-types`      | JWT  | List service types for a dealership  |
| `GET`   | `/health`                                     | —    | Health check                         |
| `GET`   | `/metrics`                                    | —    | Prometheus metrics                   |

Full cURL examples: [backend/docs/curl-examples.md](./backend/docs/curl-examples.md)  
Interactive docs (local): http://localhost:8000/docs

---

## Project Structure

```
uScheduler/
├── .github/
│   └── workflows/
│       ├── ci.yml          Lint + test + image smoke-test on every push
│       └── deploy.yml      Build → ECR push → ECS deploy (dev/staging/prod)
├── deploy/
│   ├── ecr-push.sh                 Build and push to ECR
│   ├── ecs-deploy.sh               Register task def revision + update service
│   └── task-definition.template.json  Template for first-time environment setup
├── Jenkinsfile             Jenkins declarative pipeline (alternative to GHA)
├── backend/
│   ├── app/
│   │   ├── api/v1/routes/  Route handlers (auth, appointments, reference)
│   │   ├── core/           Config (AWS SM loader), security, exceptions, locks, logging
│   │   ├── db/             SQLAlchemy async engine + session
│   │   ├── models/         ORM models
│   │   ├── repositories/   DB query layer
│   │   ├── schemas/        Pydantic request/response schemas
│   │   └── services/       Domain logic (BookingService, AuthService)
│   ├── alembic/            Database migrations
│   ├── scripts/seed.py     Demo data seeder
│   ├── tests/
│   │   ├── unit/           Service unit tests (SQLite + fakeredis)
│   │   └── integration/    Full HTTP tests via AsyncClient
│   ├── Dockerfile          Multi-stage: dev (hot-reload) / runtime (production)
│   ├── docker-compose.yml  Local development stack
│   └── pyproject.toml
└── docs/system-design/     Design documents and diagrams
```


---
