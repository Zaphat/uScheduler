# cURL Examples — uScheduler API

All requests target `http://localhost:8000/api/v1`.  
Replace token, IDs, and dates with values from the seed output.

---

## 1. Register a customer

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Jane Smith","email":"jane@example.com","password":"Password123"}' | jq
```

## 2. Log in and capture the token

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@example.com","password":"Password123"}' \
  | jq -r '.access_token')
echo $TOKEN
```

## 3. Check available slots

```bash
curl -s "http://localhost:8000/api/v1/availability?\
dealership_id=d0000000-0000-0000-0000-000000000001&\
service_type_id=s0000000-0000-0000-0000-000000000001&\
date=2026-06-20" \
  -H "Authorization: Bearer $TOKEN" | jq
```

## 4. Book an appointment

```bash
curl -s -X POST http://localhost:8000/api/v1/appointments \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "vehicle_id":       "v0000000-0000-0000-0000-000000000001",
    "dealership_id":    "d0000000-0000-0000-0000-000000000001",
    "service_type_id":  "s0000000-0000-0000-0000-000000000001",
    "scheduled_start":  "2026-06-20T09:00:00Z"
  }' | jq
```

## 5. Get an appointment

```bash
APPT_ID=<id-from-step-4>
curl -s "http://localhost:8000/api/v1/appointments/$APPT_ID" \
  -H "Authorization: Bearer $TOKEN" | jq
```

## 6. List my appointments

```bash
curl -s "http://localhost:8000/api/v1/appointments?page=1&limit=20" \
  -H "Authorization: Bearer $TOKEN" | jq
```

## 7. Cancel an appointment

```bash
curl -s -X PATCH "http://localhost:8000/api/v1/appointments/$APPT_ID/cancel" \
  -H "Authorization: Bearer $TOKEN" | jq
```

## 8. List dealerships

```bash
curl -s "http://localhost:8000/api/v1/dealerships" \
  -H "Authorization: Bearer $TOKEN" | jq
```

## 9. List service types for a dealership

```bash
curl -s "http://localhost:8000/api/v1/dealerships/d0000000-0000-0000-0000-000000000001/service-types" \
  -H "Authorization: Bearer $TOKEN" | jq
```

## 10. Health check

```bash
curl -s http://localhost:8000/health | jq
```

---

The interactive OpenAPI docs are available at **http://localhost:8000/docs** when the server is running.
