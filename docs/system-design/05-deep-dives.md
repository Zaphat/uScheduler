# 05 — Deep Dives

## Deep Dive 1 — Preventing Double-Booking Under Concurrency

### The Problem

Two customers simultaneously request the same bay + technician + timeslot. Both execute
the availability query at the same millisecond and both see the slot as free. Without a
guard, both writes succeed and a double-booking occurs.

### Three-Layer Defence

```
Layer 1: Redis Distributed Lock   ← stops the race in practice
Layer 2: DB Transaction + Re-check ← catches gaps in the lock
Layer 3: DB Unique/Exclusion Constraint ← final backstop, never relies on app logic
```

---

#### Layer 1 — Redis Distributed Lock

After selecting a candidate bay and technician, the service acquires two locks before
touching the database:

```
SET lock:bay:{bayId}:{slotKey}   {requestId}  NX  PX 30000
SET lock:tech:{techId}:{slotKey} {requestId}  NX  PX 30000
```

- `NX` — only set if key does not exist (atomic compare-and-set)
- `PX 30000` — 30-second TTL; lock auto-expires if the server crashes mid-request
- `{slotKey}` — derived from `floor(scheduledStart / 15min)` so the lock is scoped to a
  time bucket rather than the exact second, reducing key space

If either lock fails, return `409 SLOT_UNAVAILABLE`. No DB write happens.

**Lock release** — always happens in a `finally` block, even on error, using the stored
`{requestId}` to ensure only the lock owner can delete it:

```lua
-- Lua script executed atomically in Redis
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
else
  return 0
end
```

This is the standard Redlock pattern for a single-node Redis.

---

#### Layer 2 — DB Transaction with Re-Check

Inside the transaction, before inserting, the service re-runs the overlap query:

```sql
SELECT 1
FROM   appointments
WHERE  service_bay_id = $1
  AND  status = 'CONFIRMED'
  AND  scheduled_start < $3          -- $3 = requested end
  AND  scheduled_end   > $2          -- $2 = requested start
LIMIT  1;
```

If a row is found, the transaction is rolled back and `409` is returned. The Redis lock
is then released.

This re-check catches the edge case where:
- Two requests target different bays but one bay lookup falls through due to timing
- The Redis lock TTL expired during a slow DB operation

---

#### Layer 3 — PostgreSQL Partial Unique / Exclusion Constraint

As a final backstop, a `DEFERRABLE` exclusion constraint is added using the
`btree_gist` extension:

```sql
ALTER TABLE appointments
  ADD CONSTRAINT no_double_bay_booking
  EXCLUDE USING gist (
    service_bay_id WITH =,
    tstzrange(scheduled_start, scheduled_end, '[)') WITH &&
  )
  WHERE (status = 'CONFIRMED');
```

If any bug in the application layer still produces a conflicting INSERT, PostgreSQL
raises a constraint violation, the transaction rolls back, and the error propagates as
a `500` with a CloudWatch Alarm firing. This should never trigger in production — its
existence makes the system provably correct regardless of application bugs.

---

### Concurrency Timeline

```
Time →    T1                                T2
─────────────────────────────────────────────────────
 100ms    Availability query → Bay 3 free   Availability query → Bay 3 free
 120ms    LOCK bay:3:slot → SUCCESS
 125ms                                      LOCK bay:3:slot → FAIL (409 returned)
 130ms    BEGIN TRANSACTION
 135ms    Re-check → no conflict found
 140ms    INSERT appointment
 145ms    COMMIT
 150ms    RELEASE lock
 155ms    Return 201 ✓
```

Request T2 is rejected cleanly at the lock layer. Bay 3 has exactly one confirmed
appointment.

---

## Deep Dive 2 — Availability Algorithm

### The Overlap Query

Finding a free slot for a time window `[start, end)` means finding a resource that has
**no** confirmed appointment whose interval overlaps `[start, end)`.

Two intervals `[a, b)` and `[c, d)` overlap when `a < d AND b > c`.
The **non**-overlap condition is `b ≤ c OR a ≥ d`.

The SQL to find available bays:

```sql
SELECT sb.id, sb.label
FROM   service_bays sb
WHERE  sb.dealership_id = $1
  AND  sb.is_active = true
  AND  NOT EXISTS (
    SELECT 1
    FROM   appointments a
    WHERE  a.service_bay_id = sb.id
      AND  a.status = 'CONFIRMED'
      AND  a.scheduled_start < $3   -- requested_end
      AND  a.scheduled_end   > $2   -- requested_start
  )
LIMIT  1;
```

Same structure for technicians, with an additional skill-match filter:

```sql
SELECT t.id, t.name
FROM   technicians t
WHERE  t.dealership_id = $1
  AND  t.is_active = true
  AND  t.skills @> $4               -- $4 = service_type.required_skills (GIN index)
  AND  NOT EXISTS (
    SELECT 1
    FROM   appointments a
    WHERE  a.technician_id = t.id
      AND  a.status = 'CONFIRMED'
      AND  a.scheduled_start < $3
      AND  a.scheduled_end   > $2
  )
LIMIT  1;
```

### Index Strategy

| Table | Index | Purpose |
|-------|-------|---------|
| `appointments` | `(service_bay_id, status, scheduled_start, scheduled_end)` | Covers bay overlap sub-query |
| `appointments` | `(technician_id, status, scheduled_start, scheduled_end)` | Covers technician overlap sub-query |
| `technicians` | GIN on `skills` | Covers `skills @> required_skills` filter |
| `appointments` | GIN/GiST `tstzrange` (exclusion constraint) | Powers the Layer 3 backstop |

With these indexes, each availability query is an index scan + nested loop — no sequential
scan of the `appointments` table.

---

### Available Slots Enumeration (GET /availability)

To list all available start times for a given day, the service generates candidate
30-minute slots within the dealership's operating hours, then filters out any slot where
**zero** bays or **zero** qualified technicians are free.

```
operating_hours = dealership.opening_time → dealership.closing_time
slot_duration   = service_type.duration_minutes
candidate_slots = every slot_duration increment within operating_hours

for each slot in candidate_slots:
  if bay_available(slot) AND tech_available(slot):
    yield slot
```

This runs in **3 database queries** followed by in-process filtering to avoid N+1 round trips:

1. Fetch all active bays for the dealership
2. Fetch all active technicians for the dealership
3. Fetch all CONFIRMED appointments overlapping the full operating day

Candidate slots are then iterated in Python, and each slot is tested by computing the set of occupied bays and technicians from the pre-fetched appointments:

```python
for each slot in candidate_slots:
    occupied_bays  = {a.service_bay_id  for a in day_appointments if overlaps(a, slot)}
    occupied_techs = {a.technician_id   for a in day_appointments if overlaps(a, slot)}
    if (bay_ids - occupied_bays) and (qualified_tech_ids - occupied_techs):
        yield slot
```

This is O(slots × appointments) per request but avoids repeated round trips to the database.

Result is cached in Redis for 60 seconds per `(dealership_id, service_type_id, date)`
key to absorb read spikes without hitting the DB.

---

## Deep Dive 3 — Observability Strategy

### Three Pillars

#### Logs (structlog → CloudWatch Logs)

The Python API uses **structlog** for structured JSON logging. ECS ships stdout to
**Amazon CloudWatch Logs** automatically via the `awslogs` log driver — no sidecar
or agent needed. Every HTTP request and booking attempt emits:

```json
{
  "level": "info",
  "timestamp": "2026-06-01T14:23:11.045Z",
  "request_id": "req-abc123",
  "method": "POST",
  "path": "/api/v1/appointments",
  "customer_id": "c1d2e3f4-...",
  "dealership_id": "d1a2b3c4-...",
  "outcome": "CONFIRMED",
  "duration_ms": 142,
  "event": "appointment_confirmed"
}
```

CloudWatch Log Insights queries let the support team filter by `customer_id`,
`dealership_id`, or `outcome` without leaving the AWS console.

---

#### Metrics (Prometheus → Grafana)

The FastAPI app exposes a `/metrics` endpoint via
`prometheus-fastapi-instrumentator`. **Prometheus** scrapes this endpoint on a
configurable interval and stores time-series data.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `appointments_requested_total` | Counter | `dealership_id`, `service_type` | Total booking attempts |
| `appointments_confirmed_total` | Counter | `dealership_id`, `service_type` | Successful bookings |
| `appointments_rejected_total` | Counter | `dealership_id`, `reason` | Rejections (no bay / no tech / lock) |
| `availability_query_duration_seconds` | Histogram | `dealership_id` | Latency of the slot availability query |
| `booking_duration_seconds` | Histogram | `outcome` | End-to-end booking request latency |
| `redis_lock_acquisitions_total` | Counter | `resource`, `result` | Lock success/failure rate |

**Grafana** connects to Prometheus as a data source and provides:
- Dashboards for booking throughput, P99 latency, and lock contention
- Alert rules that notify on-call when thresholds are breached:
  - Booking rejection rate > 30% over 5 min
  - P99 `booking_duration_seconds` > 1.0 s for 3 min
  - SQS DLQ message count > 0 (notification delivery failure)

---

## Deep Dive 4 — Idempotency

A client that does not receive a response (network timeout) may retry. Without
idempotency, the retry could create a second confirmed appointment for the same customer
at the same time.

### Implementation

1. Client sends `Idempotency-Key: <uuid>` header with `POST /appointments`
2. The Booking API checks ElastiCache for key `idem:{customerId}:{key}`. On a hit,
   the cached response is returned immediately without re-executing booking logic.
3. On a miss, booking proceeds normally. The confirmed response is stored in
   ElastiCache with TTL = 24 h before returning to the client.

> **Why in the API rather than the gateway?** AWS API Gateway HTTP API does not
> natively cache responses by a custom header. Handling it in the FastAPI service
> keeps the logic visible and testable.

The key is scoped to the authenticated customer (the JWT `sub` claim is part of the
Redis key) so one customer cannot observe or replay another customer's idempotency key.

```
key format: idempotency:{customerId}:{idempotency-key-header-value}
```

---

## Deep Dive 5 — Security

| Concern | Control |
|---------|---------|
| Authentication | JWTs signed with RS256 (asymmetric); AWS API Gateway JWT authorizer validates against the JWKS endpoint — no DB roundtrip |
| Authorisation | RBAC enforced in the FastAPI service layer: `CUSTOMER` role can only access own data; `STAFF` scoped to own dealership |
| SQL injection | SQLAlchemy 2 uses bound parameters exclusively; no raw string interpolation in queries |
| Sensitive data exposure | `password_hash` is never returned in any API response; Pydantic response models use field exclusion to enforce this at the serialisation layer |
| Rate limiting | Configured at AWS API Gateway stage level: 60 req/min per customer, 10 booking attempts/min per customer |
| HTTPS | TLS 1.3 managed by AWS API Gateway and CloudFront; no plaintext HTTP endpoints |
| Secrets management | Aurora credentials, ElastiCache endpoint, JWT keys stored in **AWS Secrets Manager**; ECS tasks access secrets via IAM task role — no environment variable injection of plaintext secrets |
| IAM least-privilege | ECS task role has only the permissions it needs: `secretsmanager:GetSecretValue` for its own secrets, `sqs:SendMessage` to the notification queue, `xray:PutTraceSegments` |
| Network isolation | ECS tasks, Aurora, and ElastiCache all run inside a VPC with no public subnets; API Gateway reaches ECS via VPC Link |
