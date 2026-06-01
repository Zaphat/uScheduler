# Diagram 03 — Booking Flow (Sequence)

End-to-end sequence for a successful appointment booking and the two main failure paths.

```mermaid
sequenceDiagram
    actor       C  as Customer
    participant GW as API Gateway
    participant AS as Booking API
    participant RD as Redis
    participant PG as PostgreSQL
    participant Q  as SQS
    participant NS as Lambda Worker

    C  ->>  GW : POST /appointments
    GW ->>  GW : Verify JWT · rate limit · idempotency key
    GW ->>  AS : Forward request

    AS ->>  PG : Validate ownership, dealership, service type, operating hours
    alt Validation fails
        AS -->> C : 400 Bad Request
    end

    AS ->>  PG : Query available service bay (no overlap in [start, end))
    AS ->>  PG : Query available technician (skills match, no overlap)
    alt No bay or technician available
        AS -->> C : 409 SLOT_UNAVAILABLE
    end

    AS ->>  RD : SET lock:bay:{id}:{slot} NX PX 30000
    AS ->>  RD : SET lock:tech:{id}:{slot} NX PX 30000
    alt Lock not acquired
        AS ->>  RD : Release any acquired lock
        AS -->> C : 409 SLOT_TAKEN
    end

    AS ->>  PG : BEGIN — re-check bay & technician overlap
    alt Overlap detected
        AS ->>  PG : ROLLBACK
        AS ->>  RD : Release locks
        AS -->> C : 409 SLOT_UNAVAILABLE
    end

    AS ->>  PG : INSERT appointment · COMMIT
    AS ->>  RD : Release locks (Lua CAS)
    AS ->>  Q  : SendMessage BOOKING_CONFIRMATION
    AS -->> C  : 201 Created

    Q  ->>  NS : Deliver job
    NS ->>  NS : Send email (SES) · Send SMS (SNS)
```

## Notes

- **Idempotency**: If the customer retries with the same `Idempotency-Key` header,
  ElastiCache returns the cached `201` response without re-executing booking logic.
- **Lock TTL**: The 30-second TTL ensures locks are released even if the ECS task crashes
  mid-transaction. The Aurora exclusion constraint provides a final backstop in that case.
- **Notification decoupling**: A Lambda failure does not affect booking confirmation.
  SQS retries delivery up to 5 times; undeliverable messages land in the DLQ.
