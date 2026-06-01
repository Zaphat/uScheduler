# uScheduler — System Design Document

> Appointment Scheduler to replace manual dealership booking systems.

---

## Document Index

| # | Document | Description |
|---|----------|-------------|
| 1 | [Requirements](./docs/system-design/01-requirements.md) | Functional, non-functional requirements and constraints |
| 2 | [Core Entities](./docs/system-design/02-core-entities.md) | Domain model, data schema, ER diagram |
| 3 | [API Design](./docs/system-design/03-api-design.md) | REST endpoints, request/response contracts |
| 4 | [High-Level Design](./docs/system-design/04-high-level-design.md) | Architecture overview, components, technology choices |
| 5 | [Deep Dives](./docs/system-design/05-deep-dives.md) | Concurrency, availability algorithm, indexing, observability |

## Diagrams

| Diagram | Description |
|---------|-------------|
| [Architecture](./docs/system-design/diagrams/01-architecture.md) | System component diagram |
| [Entity Relationship](./docs/system-design/diagrams/02-entity-relationship.md) | Data model ER diagram |
| [Booking Flow](./docs/system-design/diagrams/03-booking-flow.md) | End-to-end sequence diagram |
| [Availability Check](./docs/system-design/diagrams/04-availability-check.md) | Decision flowchart |

---

## Problem Statement

Dealerships manage service appointments manually — phone calls, paper logs, shared
spreadsheets — leading to double-bookings, underutilised bays, and poor customer
experience. uScheduler replaces this with an API-first booking system that enforces
resource constraints in real time.

## Core Constraints

1. A **ServiceBay** can hold exactly one vehicle at a time.
2. A **Technician** can work on exactly one vehicle at a time.
3. A **Technician** must possess all skills required by the selected **ServiceType**.
4. An **Appointment** duration is fixed by the **ServiceType** — it cannot be shortened.

## Key Design Decisions (Summary)

| Decision | Choice | Reason |
|----------|--------|--------|
| Service architecture | Modular monolith (single ECS service) + separate Notification Lambda | Single bounded context; distributed transactions not warranted; Lambda isolates async failures |
| Backend language | Python 3.12 + FastAPI | Async I/O, concise business logic, strong AWS SDK ecosystem |
| Frontend framework | Next.js 15 (TypeScript) | Most widely adopted TypeScript-first React framework; SSR; large ecosystem |
| Cloud provider | AWS | Full managed-service coverage reduces operational overhead |
| Booking atomicity | Aurora PostgreSQL transaction + ElastiCache Redis lock | Prevents double-booking under concurrent load |
| Availability query | Gap-based overlap query with composite indexes | Efficient without a full table scan |
| Async notifications | Amazon SQS + Lambda | Decouples confirmation email/SMS from the critical path; SQS DLQ for retry |
| Observability | Prometheus + Grafana + CloudWatch Logs | Prometheus scrapes API metrics; Grafana for dashboards and alerts; CloudWatch Logs for structured log ingestion |
