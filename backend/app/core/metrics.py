"""Domain-level Prometheus metrics for the uScheduler booking service.

Instantiated once at import time. Collected alongside the generic HTTP metrics
exposed by prometheus-fastapi-instrumentator on /metrics.
"""
from prometheus_client import Counter, Histogram

appointments_requested = Counter(
    "appointments_requested_total",
    "Total booking attempts (excludes idempotent replays)",
    ["dealership_id", "service_type_id"],
)

appointments_confirmed = Counter(
    "appointments_confirmed_total",
    "Successful bookings",
    ["dealership_id", "service_type_id"],
)

appointments_rejected = Counter(
    "appointments_rejected_total",
    "Rejected bookings (no bay / no tech / lock contention / outside hours)",
    ["dealership_id", "reason"],
)

availability_query_duration = Histogram(
    "availability_query_duration_seconds",
    "Latency of the slot availability query",
    ["dealership_id"],
)

booking_duration = Histogram(
    "booking_duration_seconds",
    "End-to-end booking request latency",
    ["outcome"],
)

redis_lock_acquisitions = Counter(
    "redis_lock_acquisitions_total",
    "Redis lock acquisition attempts",
    ["resource", "result"],
)
