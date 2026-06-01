# Diagram 02 — Entity Relationship

```mermaid
erDiagram
    CUSTOMER {
        uuid        id              PK
        varchar     name
        varchar     email
        varchar     phone
        varchar     password_hash
        timestamptz created_at
    }

    VEHICLE {
        uuid        id              PK
        uuid        customer_id     FK
        varchar     make
        varchar     model
        smallint    year
        varchar     vin
        varchar     license_plate
    }

    DEALERSHIP {
        uuid        id              PK
        varchar     name
        text        address
        varchar     timezone
        time        opening_time
        time        closing_time
    }

    SERVICE_TYPE {
        uuid        id               PK
        varchar     name
        text        description
        int         duration_minutes
        text_array  required_skills
    }

    SERVICE_BAY {
        uuid        id              PK
        uuid        dealership_id   FK
        varchar     label
        boolean     is_active
    }

    TECHNICIAN {
        uuid        id              PK
        uuid        dealership_id   FK
        varchar     name
        text_array  skills
        boolean     is_active
    }

    APPOINTMENT {
        uuid        id              PK
        uuid        customer_id     FK
        uuid        vehicle_id      FK
        uuid        dealership_id   FK
        uuid        service_type_id FK
        uuid        service_bay_id  FK
        uuid        technician_id   FK
        timestamptz scheduled_start
        timestamptz scheduled_end
        varchar     status
        timestamptz created_at
        timestamptz updated_at
        timestamptz cancelled_at
    }

    CUSTOMER     ||--o{ VEHICLE      : "owns"
    CUSTOMER     ||--o{ APPOINTMENT  : "books"
    VEHICLE      ||--o{ APPOINTMENT  : "serviced in"
    DEALERSHIP   ||--o{ SERVICE_BAY  : "has"
    DEALERSHIP   ||--o{ TECHNICIAN   : "employs"
    DEALERSHIP   ||--o{ APPOINTMENT  : "hosts"
    SERVICE_TYPE ||--o{ APPOINTMENT  : "defines"
    SERVICE_BAY  ||--o{ APPOINTMENT  : "allocated to"
    TECHNICIAN   ||--o{ APPOINTMENT  : "assigned to"
```

## Key Constraints

| Constraint | Enforcement |
|-----------|-------------|
| `vehicle.customer_id = appointment.customer_id` | Application layer + FK |
| `service_bay.dealership_id = appointment.dealership_id` | Application layer + FK |
| `technician.dealership_id = appointment.dealership_id` | Application layer + FK |
| `technician.skills @> service_type.required_skills` | Application layer + GIN index query |
| No overlapping CONFIRMED appointments per bay | Exclusion constraint (`tstzrange && WITH gist`) |
| No overlapping CONFIRMED appointments per technician | Exclusion constraint (`tstzrange && WITH gist`) |
