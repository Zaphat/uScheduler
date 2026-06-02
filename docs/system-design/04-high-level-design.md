# 04 — High-Level Design

## 1. Architecture Overview

See [diagrams/01-architecture.md](./diagrams/01-architecture.md) for the full diagram.

The system is a **modular monolith** deployed on AWS, backed by Amazon Aurora PostgreSQL
for durable storage and Amazon ElastiCache (Redis) for distributed locking and caching.
A separate async Notification Worker (AWS Lambda + SQS) decouples email/SMS delivery from
the critical booking path.

---

## 1a. Microservices vs Modular Monolith

**Decision: Modular Monolith.**

| Option | Pros | Cons |
|--------|------|------|
| **Microservices** | Independent deployability, per-service scaling | High operational overhead (service mesh, inter-service auth, distributed transactions), premature for this domain size |
| **Modular Monolith** | Simple deployment, single DB transaction spans the whole booking, fast iteration | Scales as one unit |

The booking domain is a **single bounded context** — Customer, Vehicle, Dealership,
Appointment all change together. Splitting them across services would require distributed
transactions (Saga pattern) to maintain the booking invariants we get for free from
PostgreSQL today. That complexity is not justified at this scale.

The **Notification Worker is the one genuine separate process** because:
- It is naturally async (decoupled from the booking critical path)
- It has different failure semantics (a crash must not roll back a confirmed booking)
- It scales independently based on notification volume

The monolith is structured in **clear modules** (`booking`, `customers`, `dealerships`,
`notifications`) so individual modules can be extracted to microservices in the future
without a full rewrite.

---

## 2. Components

### 2.1 Client Layer

| Component | Role |
|-----------|------|
| **Web App (Next.js)** | Server-side rendered React app; TypeScript throughout; hosted on AWS Amplify or as a containerised Next.js app behind CloudFront |
| **Mobile App** | Native iOS/Android app; communicates over the same REST API |

Next.js provides SSR for fast initial loads and collocates data-fetching with components.
Both clients are thin — all business logic lives server-side.

---

### 2.2 API Gateway

**AWS API Gateway (HTTP API)** sits in front of the Booking API. Responsibilities:

- **TLS termination** — all traffic is HTTPS; AWS manages the certificate via ACM
- **Rate limiting** — throttling configured at the stage level (requests/sec per route)
- **JWT verification** — Lambda authorizer or Cognito authorizer validates the Bearer token before the request reaches the backend
- **Request routing** — routes `/api/v1/*` to the ECS Fargate service via VPC Link
- **Idempotency key deduplication** — handled in ElastiCache (see §2.5)

HTTP API is preferred over REST API: lower latency, lower cost, and native JWT authorizer support. The tradeoff (no request/response transformation, no built-in API caching) is acceptable.

---

### 2.3 Booking API (Core Service)

A **Python + FastAPI** application deployed on **AWS ECS Fargate**. FastAPI's async runtime handles concurrent I/O-bound requests without threads.

| Layer | Responsibility |
|-------|---------------|
| **Route handlers** | FastAPI path operations; Pydantic v2 models for request/response validation |
| **Service layer** | Orchestrates availability check, lock acquisition, DB write |
| **Repository layer** | All SQL via SQLAlchemy 2 (async engine) + Alembic migrations |
| **Lock client** | Thin wrapper around `redis-py` asyncio `SET NX PX` commands |

The service is **stateless** — any number of ECS tasks can run behind an ALB.
Shared state (locks, cached slots) lives in ElastiCache, not in process memory.

ECS Fargate is chosen over Lambda for the Booking API because:
- Booking requests can take 100–500 ms; Lambda cold starts add unacceptable P99 latency
- Persistent DB connection pools (via asyncpg) are efficient on long-running containers
- Easier to right-size CPU/memory for predictable latency

---

### 2.4 Amazon Aurora PostgreSQL (Primary Database)

**Amazon Aurora PostgreSQL Serverless v2** stores all durable domain data.

Key characteristics used:
- **ACID transactions** — the final `INSERT appointment` happens inside a transaction
  that also re-validates availability, preventing races that slip through the Redis lock
- **GIN indexes** on `skills` text arrays for fast technician qualification queries
- **Exclusion constraints** on `tstzrange` as the final booking consistency backstop
- **Aurora Serverless v2** automatically scales ACUs (Aurora Capacity Units) from a
  configured minimum, so the database handles burst booking traffic without manual
  instance resizing

The API connects via **RDS Proxy** to pool and multiplex connections, preventing PostgreSQL connection exhaustion as task count scales.

---

### 2.5 Amazon ElastiCache for Redis

**ElastiCache Serverless (Redis)** — three distinct uses:

| Use | Mechanism | TTL |
|-----|-----------|-----|
| **Distributed lock** | `SET lock:<resource>:<slot> <request-id> NX PX 30000` | 30 s |
| **Availability cache** | Hash of free slots per dealership per date | 60 s |
| **Idempotency cache** | `idem:{customerId}:{key}` → serialised response | 24 h |

ElastiCache Serverless is managed Multi-AZ Redis with no node provisioning. The API connects within the VPC; no public endpoint is exposed.

---

### 2.6 Notification Worker (AWS Lambda + SQS)

On booking confirmation, the API publishes to an **Amazon SQS** queue. A **Lambda function** (Python) consumes it and dispatches notifications.
It scales to zero when idle, and failures do not affect booking confirmation.

Responsibilities:
- Send booking confirmation emails via **Amazon SES**
- Send SMS confirmations via **Amazon SNS**
- SQS dead-letter queue (DLQ) captures messages that fail after 5 attempts for manual
  inspection and replay

SQS provides built-in DLQ, visibility timeout, and at-least-once delivery with no Redis dependency for the notification path.

---

### 2.7 Observability Stack

| Tool | Role |
|------|------|
| **Amazon CloudWatch Logs** | Structured JSON logs from the API and Lambda worker. ECS ships logs automatically via the `awslogs` log driver — zero extra configuration. |
| **Prometheus** | Scrapes the `/metrics` endpoint exposed by the FastAPI app via `prometheus-fastapi-instrumentator`. Stores time-series metric data. |
| **Grafana** | Connects to Prometheus as a data source. Provides dashboards for booking throughput, latency histograms, lock contention, and DLQ depth. Alert rules notify on-call when thresholds are breached. |

---

## 3. Data Flow — Happy Path

```
1. Customer submits POST /appointments
2. API Gateway verifies JWT, rate-checks, forwards request
3. Booking API validates input (vehicle ownership, dealership exists, start time valid)
4. Service layer computes scheduled_end = scheduled_start + service_type.duration_minutes
5. Availability query: SELECT bays and technicians with no overlapping CONFIRMED appointment
6. If none found → return 409 immediately (no lock needed)
7. Pick first available bay + technician
8. Acquire Redis locks:  SET lock:bay:<bay_id>:<slot>  NX PX 30000
                         SET lock:tech:<tech_id>:<slot> NX PX 30000
9. If lock fails → return 409 (concurrent request won the slot)
10. Open PostgreSQL transaction:
    a. Re-check overlap (defence-in-depth against lock gap edge cases)
    b. INSERT INTO appointments (...) VALUES (...) RETURNING *
    c. COMMIT
11. Release Redis locks
12. Publish SQS message: { type: 'BOOKING_CONFIRMATION', appointmentId }
13. Return 201 with full appointment object
14. Lambda worker asynchronously sends email (SES) + SMS (SNS)
```

---

## 4. Technology Choices & Justifications

### Backend

| Technology | Choice | Justification |
|-----------|--------|---------------|
| **Language** | Python 3.12 | Strong async support via `asyncio`; rich data/web ecosystem; concise for business logic |
| **Web framework** | FastAPI | Async-native, automatic OpenAPI docs, Pydantic v2 validation built-in, high throughput for I/O-bound workloads |
| **ORM** | SQLAlchemy 2 (async) | Industry-standard Python ORM; async engine (`asyncpg`) avoids blocking the event loop on DB calls |
| **Migrations** | Alembic | Pairs with SQLAlchemy; version-controlled, reversible schema migrations |
| **Redis client** | redis-py (asyncio) | Official Python Redis client; async API matches the FastAPI event loop |
| **AWS SDK** | boto3 / aioboto3 | Official AWS SDK; `aioboto3` provides async wrappers for SQS/SES/SNS calls |

### Frontend

| Technology | Choice | Justification |
|-----------|--------|---------------|
| **Framework** | Next.js 15 (App Router) | Most widely adopted TypeScript-first React framework; SSR reduces time-to-first-paint; collocated data fetching; large ecosystem |
| **Language** | TypeScript | End-to-end type safety; API response types can be shared from an OpenAPI-generated client |
| **Styling** | Tailwind CSS | Utility-first; no CSS-in-JS runtime cost; good fit for component-heavy UIs |

### Infrastructure (AWS)

| Technology | Choice | Justification |
|-----------|--------|---------------|
| **Compute (API)** | AWS ECS Fargate | Serverless containers; no EC2 management; right-sized for persistent connection pools and low P99 latency |
| **Compute (Worker)** | AWS Lambda (Python) | Event-driven; scales to zero; SQS trigger handles concurrency automatically |
| **API Gateway** | AWS API Gateway HTTP API | Managed ingress; native JWT authorizer; VPC Link to ECS |
| **Database** | Amazon Aurora PostgreSQL Serverless v2 | Auto-scaling ACUs; ACID; RDS Proxy for connection pooling |
| **Cache / Lock** | Amazon ElastiCache Serverless (Redis) | Managed Multi-AZ Redis; no node provisioning; same Redis primitives (`SET NX PX`) |
| **Queue** | Amazon SQS | Managed, durable, at-least-once delivery; DLQ captures messages that fail after 5 attempts |
| **Email** | Amazon SES | AWS-native; cost-effective at scale; integrated with IAM for credentials |
| **SMS** | Amazon SNS | AWS-native SMS; simple API; falls back to regional carriers automatically |
| **Frontend hosting** | AWS Amplify Hosting | Git-connected; preview deployments per PR; CloudFront CDN built-in |
| **Secrets** | AWS Secrets Manager | Centralised secret rotation; ECS tasks access secrets via IAM role — no hardcoded credentials |
| **Container registry** | Amazon ECR | Private registry; image scanning; integrates with ECS task definitions |
| **Observability** | CloudWatch Logs + Prometheus + Grafana | CloudWatch Logs is zero-config with ECS; Prometheus + Grafana is the industry standard for metrics dashboards and alerting |
| **IaC** | AWS CDK (TypeScript) | Programmatic infrastructure definition; type-safe; reuses developer TypeScript knowledge |

---

## 5. Deployment Topology (AWS)

```
 Internet
    │  HTTPS
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  AWS Account  (us-east-1)                                       │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  CloudFront + Amplify Hosting  (Next.js Web App)         │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │ API calls                           │
│  ┌───────────────────────▼──────────────────────────────────┐  │
│  │  AWS API Gateway (HTTP API)                              │  │
│  │  JWT Authorizer · Rate Limiting · VPC Link               │  │
│  └───────────────────────┬──────────────────────────────────┘  │
│                          │                                     │
│  ┌── VPC ────────────────▼──────────────────────────────────┐  │
│  │                                                          │  │
│  │  ALB ──► ECS Fargate (Booking API, Python/FastAPI)       │  │
│  │              Task x2  (rolling deploy)                   │  │
│  │                   │              │                       │  │
│  │                   ▼              ▼                       │  │
│  │            RDS Proxy      ElastiCache Serverless         │  │
│  │                │          (Redis — lock + cache)         │  │
│  │                ▼                                         │  │
│  │     Aurora PostgreSQL Serverless v2                      │  │
│  │     (Primary + Auto-scaling ACUs)                        │  │
│  │                                                          │  │
│  │  SQS Queue ──► Lambda (Notification Worker, Python)      │  │
│  │  SQS DLQ       └──► SES (email) + SNS (SMS)              │  │
│  │                                                          │  │
│  │  awslogs driver ──► CloudWatch Logs                       │  │
│  │  /metrics endpoint ──► Prometheus ──► Grafana             │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  AWS Secrets Manager · ECR · CDK (IaC)                         │
└─────────────────────────────────────────────────────────────────┘
```

Two ECS tasks behind an ALB provide basic redundancy and enable rolling deploys with
zero downtime. ElastiCache distributed locks ensure booking correctness across both tasks.

---

## 6. Future Scaling Considerations

| Bottleneck | Solution |
|-----------|----------|
| Aurora write throughput | Aurora Serverless v2 scales ACUs automatically; add an Aurora read replica for the availability query read path |
| Connection exhaustion | RDS Proxy already pools connections; tune max pool size as task count grows |
| ElastiCache single-AZ | ElastiCache Serverless handles Multi-AZ replication automatically |
| Notification delivery spikes | Lambda concurrency scales automatically with SQS batch size; no manual scaling |
| API throughput beyond ECS | Evaluate AWS Lambda + Lambda Web Adapter for the API if burst patterns warrant it |
| Multi-region | Aurora Global Database for <1s cross-region replication; Route 53 latency-based routing |
| Microservice extraction | Because the monolith is modular, the `Dealerships` or `Customers` module can be extracted to a separate ECS service + its own Aurora cluster when team size or traffic justify it |
