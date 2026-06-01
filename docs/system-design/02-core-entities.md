# 02 — Core Entities

## 1. Domain Model Overview

```
Customer ──owns──► Vehicle
    │
    └──books──► Appointment ◄──scheduled at──► Dealership
                    │                               │
                    ├──defines──► ServiceType       ├──has──► ServiceBay
                    ├──uses──────► ServiceBay        └──employs──► Technician
                    └──assigned──► Technician
```

---

## 2. Entity Definitions

### Customer
Represents an end user who owns vehicles and makes appointments.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `name` | VARCHAR(100) | Full name |
| `email` | VARCHAR(255) | Unique, used for login and notifications |
| `phone` | VARCHAR(20) | E.164 format, used for SMS notifications |
| `password_hash` | VARCHAR(255) | bcrypt hash, never returned in API responses |
| `created_at` | TIMESTAMPTZ | |

---

### Vehicle
A vehicle owned by a customer that can be brought in for service.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `customer_id` | UUID FK → Customer | |
| `make` | VARCHAR(50) | e.g. Toyota |
| `model` | VARCHAR(50) | e.g. Camry |
| `year` | SMALLINT | e.g. 2021 |
| `vin` | VARCHAR(17) | Unique Vehicle Identification Number |
| `license_plate` | VARCHAR(20) | |

---

### Dealership
A physical service location with bays and technicians.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `name` | VARCHAR(100) | |
| `address` | TEXT | |
| `timezone` | VARCHAR(50) | IANA timezone, e.g. `America/New_York` |
| `opening_time` | TIME | Daily opening time (local) |
| `closing_time` | TIME | Daily closing time (local) |

---

### ServiceType
A catalogue of services offered, each with a fixed duration and required technician skills.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `name` | VARCHAR(100) | e.g. "Full Engine Overhaul" |
| `description` | TEXT | |
| `duration_minutes` | INT | Fixed service duration |
| `required_skills` | TEXT[] | e.g. `["engine", "electrical"]` |

> **Design note**: `required_skills` is a PostgreSQL text array. An index on the GIN
> operator allows efficient `@>` (contains) queries when matching technician skills.

---

### ServiceBay
A physical workspace within a dealership. One vehicle at a time.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `dealership_id` | UUID FK → Dealership | |
| `label` | VARCHAR(20) | e.g. "Bay 3A" |
| `is_active` | BOOLEAN | Allows bays to be taken offline |

---

### Technician
A staff member assigned to appointments. Must have matching skills for the service type.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `dealership_id` | UUID FK → Dealership | |
| `name` | VARCHAR(100) | |
| `skills` | TEXT[] | e.g. `["oil", "tyres", "engine"]` |
| `is_active` | BOOLEAN | |

---

### Appointment
The central booking record. Created when both a bay and technician are successfully reserved.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `customer_id` | UUID FK → Customer | |
| `vehicle_id` | UUID FK → Vehicle | Must be owned by `customer_id` |
| `dealership_id` | UUID FK → Dealership | |
| `service_type_id` | UUID FK → ServiceType | |
| `service_bay_id` | UUID FK → ServiceBay | Assigned during booking |
| `technician_id` | UUID FK → Technician | Assigned during booking |
| `scheduled_start` | TIMESTAMPTZ | Requested by customer |
| `scheduled_end` | TIMESTAMPTZ | Computed: `scheduled_start + duration_minutes` |
| `status` | ENUM | `PENDING`, `CONFIRMED`, `CANCELLED`, `COMPLETED` |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |
| `cancelled_at` | TIMESTAMPTZ | Nullable |

#### Status Transitions

```
             ┌──────────────────────────────────────────────────┐
             │                                                  │
  [request]  ▼                                                  │
  ──────► PENDING ──[resources found]──► CONFIRMED ──[time passes]──► COMPLETED
              │                               │
              │ [no resources / error]        │ [customer cancels]
              ▼                               ▼
           FAILED                         CANCELLED
```

---

## 3. Relationships Summary

| Relationship | Cardinality | Notes |
|-------------|-------------|-------|
| Customer → Vehicle | 1 : N | A customer can own many vehicles |
| Customer → Appointment | 1 : N | A customer can have many appointments |
| Vehicle → Appointment | 1 : N | A vehicle can be serviced many times |
| Dealership → ServiceBay | 1 : N | |
| Dealership → Technician | 1 : N | |
| Dealership → Appointment | 1 : N | |
| ServiceType → Appointment | 1 : N | |
| ServiceBay → Appointment | 1 : N | No time overlap allowed |
| Technician → Appointment | 1 : N | No time overlap allowed |

---

## 4. ER Diagram

See [diagrams/02-entity-relationship.md](./diagrams/02-entity-relationship.md)

---

## 5. Key Invariants (Enforced in Application Layer + DB)

1. `appointment.vehicle_id` must have `vehicle.customer_id = appointment.customer_id`
2. `appointment.service_bay_id` must have `service_bay.dealership_id = appointment.dealership_id`
3. `appointment.technician_id` must have `technician.dealership_id = appointment.dealership_id`
4. `technician.skills @> service_type.required_skills` must be true
5. No two `CONFIRMED` appointments may share the same `service_bay_id` with overlapping `[scheduled_start, scheduled_end)` intervals
6. No two `CONFIRMED` appointments may share the same `technician_id` with overlapping `[scheduled_start, scheduled_end)` intervals
