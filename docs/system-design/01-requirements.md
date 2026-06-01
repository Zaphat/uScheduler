# 01 — Requirements

## 1. Functional Requirements

### FR-1 · Request a Service Appointment
A customer must be able to request an appointment by providing:
- Their identity (authenticated customer ID)
- The vehicle to be serviced (must be owned by the customer)
- The dealership where service will occur
- The service type (e.g., Oil Change, Tyre Rotation, Engine Overhaul)
- A desired start date and time

### FR-2 · Real-Time Availability Check
Before confirming, the system must verify that for the full service duration:
- At least one **ServiceBay** at the dealership is unoccupied
- At least one **Technician** at the dealership is both unoccupied **and** qualified for the requested service type

### FR-3 · Atomic Booking
Bay and technician must be reserved in a single atomic operation. Two simultaneous
requests for the same slot must not both succeed.

### FR-4 · Confirmed Appointment Record
On success the system persists an `Appointment` record linking:
- Customer, Vehicle, Dealership, ServiceType
- The assigned ServiceBay and Technician
- Confirmed start time, computed end time, and status = `CONFIRMED`

### FR-5 · Booking Confirmation Notification
The customer receives an email and/or SMS confirmation after a successful booking.

### FR-6 · View Appointment
A customer or staff member can retrieve appointment details by ID.

### FR-7 · Cancel Appointment
A customer can cancel a future appointment. Cancelled slots are immediately
freed for other bookings.

### FR-8 · List Available Slots
A customer can query available time slots for a given dealership + service type +
date before initiating a booking request.

---

## 2. Non-Functional Requirements

### NFR-1 · Consistency (Critical)
No double-booking. Two concurrent requests for the same bay + technician + timeslot
must result in exactly one confirmation. This takes priority over availability.

### NFR-2 · Latency
- Availability query: P99 < 300 ms
- Booking confirmation: P99 < 500 ms

### NFR-3 · Throughput
Support ≥ 500 concurrent booking requests across all dealerships without degraded consistency guarantees.

### NFR-4 · Durability
Confirmed appointments must survive application restarts. Stored in a transactional
relational database.

### NFR-5 · Observability
Every booking attempt must produce:
- A structured log entry (request, outcome, latency)
- Metrics incremented for bookings attempted, confirmed, and rejected

### NFR-6 · Availability (System Uptime)
Target 99.9 % monthly uptime for the booking API.

### NFR-7 · Security
- All endpoints require JWT authentication
- Customers may only book/view/cancel their own appointments
- Dealership staff have elevated read access scoped to their dealership

---

## 3. Constraints

| Constraint | Detail |
|-----------|--------|
| Service duration is fixed | Set by the `ServiceType`; cannot be overridden per booking |
| One vehicle per bay | A bay cannot have two overlapping appointments |
| One job per technician | A technician cannot have two overlapping appointments |
| Technician qualification | A technician's `skills` array must be a superset of the service type's `required_skills` |
| Dealership scoping | Bays and technicians belong to exactly one dealership |

---

## 4. Out of Scope

- Payment processing
- Multi-bay services (a single job spanning more than one bay)
- Parts inventory management
- Customer-facing rescheduling (cancel + rebook is the supported flow)
- Multi-tenant SaaS billing
