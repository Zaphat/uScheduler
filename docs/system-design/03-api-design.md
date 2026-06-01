# 03 — API Design

All endpoints are served under `/api/v1`. All requests and responses use `application/json`.
Authentication is required on all endpoints via `Authorization: Bearer <JWT>`.

---

## Base URL

```
https://api.uscheduler.io/api/v1
```

---

## Error Response Format

All errors follow a consistent envelope:

```json
{
  "error": {
    "code": "SLOT_UNAVAILABLE",
    "message": "No available service bay found for the requested time window.",
    "details": {}
  }
}
```

| HTTP Status | When Used |
|-------------|-----------|
| 400 | Validation failure (bad input) |
| 401 | Missing or invalid JWT |
| 403 | Authenticated but not authorised (e.g. accessing another customer's appointment) |
| 404 | Resource not found |
| 409 | Booking conflict (no bay, no technician, or concurrent lock collision) |
| 500 | Unexpected server error |

---

## Endpoints

### 1. Check Available Slots

**Purpose**: Let a customer explore availability before committing to a booking.

```
GET /availability
```

**Query Parameters**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `dealership_id` | UUID | Yes | |
| `service_type_id` | UUID | Yes | |
| `date` | ISO 8601 date (`YYYY-MM-DD`) | Yes | Local date at the dealership |

**Response 200**

```json
{
  "dealership_id": "d1a2b3c4-...",
  "service_type_id": "e5f6a7b8-...",
  "date": "2026-06-15",
  "slots": [
    { "start": "2026-06-15T09:00:00Z", "end": "2026-06-15T10:00:00Z" },
    { "start": "2026-06-15T11:00:00Z", "end": "2026-06-15T12:00:00Z" }
  ]
}
```

> Slots are returned in UTC. The client is responsible for display conversion.
> A slot appears only when **at least one bay AND one qualified technician** are free.

---

### 2. Create Appointment (Book)

**Purpose**: Request and confirm a service appointment.

```
POST /appointments
```

**Request Body**

```json
{
  "vehicle_id": "v1a2b3c4-...",
  "dealership_id": "d1a2b3c4-...",
  "service_type_id": "s1a2b3c4-...",
  "scheduled_start": "2026-06-15T09:00:00Z"
}
```

| Field | Type | Required | Validation |
|-------|------|----------|-----------|
| `vehicle_id` | UUID | Yes | Must be owned by the authenticated customer |
| `dealership_id` | UUID | Yes | Must exist |
| `service_type_id` | UUID | Yes | Must exist |
| `scheduled_start` | ISO 8601 datetime | Yes | Must be in the future; within dealership hours |

**Response 201 — Confirmed**

```json
{
  "id": "a1b2c3d4-...",
  "customer_id": "c1d2e3f4-...",
  "vehicle_id": "v1a2b3c4-...",
  "dealership_id": "d1a2b3c4-...",
  "service_type": {
    "id": "s1a2b3c4-...",
    "name": "Oil Change",
    "duration_minutes": 60
  },
  "service_bay": {
    "id": "b1a2c3d4-...",
    "label": "Bay 2"
  },
  "technician": {
    "id": "t1a2b3c4-...",
    "name": "Alex Rivera"
  },
  "scheduled_start": "2026-06-15T09:00:00Z",
  "scheduled_end": "2026-06-15T10:00:00Z",
  "status": "CONFIRMED",
  "created_at": "2026-06-01T14:23:11Z"
}
```

**Response 409 — No Resources Available**

```json
{
  "error": {
    "code": "SLOT_UNAVAILABLE",
    "message": "No qualified technician is available for the requested time window.",
    "details": {
      "requested_start": "2026-06-15T09:00:00Z",
      "requested_end": "2026-06-15T10:00:00Z"
    }
  }
}
```

---

### 3. Get Appointment

**Purpose**: Retrieve a single appointment by ID.

```
GET /appointments/:id
```

**Response 200**

Same shape as the 201 response above.

**Access control**: Customers may only fetch their own appointments. Staff may fetch any
appointment within their dealership.

---

### 4. List My Appointments

**Purpose**: Paginated list of the authenticated customer's appointments.

```
GET /appointments
```

**Query Parameters**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | ENUM | (all) | Filter by `CONFIRMED`, `CANCELLED`, `COMPLETED` |
| `page` | INT | 1 | 1-based page number |
| `limit` | INT | 20 | Max 100 |

**Response 200**

```json
{
  "data": [ /* array of appointment objects */ ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 45
  }
}
```

---

### 5. Cancel Appointment

**Purpose**: Cancel a future confirmed appointment.

```
PATCH /appointments/:id/cancel
```

**Rules**:
- Only the owning customer may cancel
- Cannot cancel an appointment whose `scheduled_start` is in the past
- Sets `status = CANCELLED` and `cancelled_at = now()`

**Response 200**

```json
{
  "id": "a1b2c3d4-...",
  "status": "CANCELLED",
  "cancelled_at": "2026-06-01T15:00:00Z"
}
```

---

## Resource Endpoints (Reference / Admin)

These are read-only by customers; write access is restricted to admin roles.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/dealerships` | List all dealerships |
| `GET` | `/dealerships/:id` | Get dealership details |
| `GET` | `/dealerships/:id/service-types` | List service types at a dealership |
| `GET` | `/service-types/:id` | Get service type details |

---

## Authentication

All endpoints require a Bearer JWT issued by the auth service.

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

JWT payload:

```json
{
  "sub": "<customer_id>",
  "role": "CUSTOMER | STAFF | ADMIN",
  "dealership_id": "<dealership_id | null>",
  "iat": 1748785391,
  "exp": 1748871791
}
```

---

## Idempotency

`POST /appointments` accepts an optional `Idempotency-Key` header (UUID). If a request
with the same key is received within 24 hours, the original response is returned without
re-executing the booking logic. This protects against client retries creating duplicate
bookings.
