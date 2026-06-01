# Diagram 04 — Availability Check (Flowchart)

Decision logic executed on every `POST /appointments` request before any lock or write.

```mermaid
flowchart TD
    A([POST /appointments]) --> B

    B{Input valid?\nowner · dealership\nservice type · hours}
    B -- No  --> C([400 Bad Request])
    B -- Yes --> D

    D["Compute scheduled_end = start + duration_minutes"]
    D --> E

    E["Query: available service bays\nno CONFIRMED overlap in [start, end)"]
    E --> F{Bay found?}
    F -- No  --> G([409 NO_BAY])
    F -- Yes --> H

    H["Query: available technicians\nskills match · no CONFIRMED overlap"]
    H --> I{Technician found?}
    I -- No  --> J([409 NO_TECHNICIAN])
    I -- Yes --> K

    K["Select bay_id + tech_id"] --> L

    L["Redis: SET lock:bay NX PX 30000\nRedis: SET lock:tech NX PX 30000"]
    L --> M{Both locks\nacquired?}
    M -- No  --> N["Release acquired lock"]
    N --> O([409 SLOT_TAKEN])
    M -- Yes --> P

    P["DB Transaction: re-check bay + technician overlap"]
    P --> Q{Conflict?}
    Q -- Yes --> R["ROLLBACK · release locks"]
    R --> S([409 SLOT_UNAVAILABLE])
    Q -- No  --> T

    T["INSERT appointment · COMMIT"]
    T --> U["Release locks · enqueue notification"]
    U --> V([201 Created])

    style C fill:#ffcccc,stroke:#cc0000,color:#000
    style G fill:#ffcccc,stroke:#cc0000,color:#000
    style J fill:#ffcccc,stroke:#cc0000,color:#000
    style O fill:#ffcccc,stroke:#cc0000,color:#000
    style S fill:#ffcccc,stroke:#cc0000,color:#000
    style V fill:#ccffcc,stroke:#006600,color:#000
```

## Decision Points Summary

| Gate | Check | Failure Response |
|------|-------|-----------------|
| **Input validation** | Schema, ownership, temporal bounds | 400 Bad Request |
| **Bay availability** | DB overlap query (`scheduled_start < end AND scheduled_end > start`) | 409 No Bay |
| **Technician availability** | DB overlap query + skill match (`skills @> required_skills`) | 409 No Technician |
| **Distributed lock** | Redis `SET NX` for bay + technician | 409 Slot Taken (concurrent) |
| **DB re-check** | Repeat overlap query inside transaction | 409 Slot Unavailable (race) |
| **DB constraint** | PostgreSQL exclusion constraint on `tstzrange` | 500 → alert (should never fire) |
