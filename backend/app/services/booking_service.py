"""Core booking service — orchestrates availability check, locking, and DB write."""
import json
import time as _time
import zoneinfo
from datetime import datetime, date as date_type, time, timezone, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SlotUnavailableError, NotFoundError, ForbiddenError, SlotTakenError
from app.core.locks import acquire_slot_locks, get_redis
from app.core.metrics import (
    appointments_requested,
    appointments_confirmed,
    appointments_rejected,
    availability_query_duration,
    booking_duration,
)
from app.core.notifications import publish_booking_confirmation
from app.models.models import Appointment
from app.repositories.appointment_repo import AppointmentRepository, ReferenceRepository
from app.schemas.schemas import AppointmentCreate

_IDEMPOTENCY_TTL_S = 86_400  # 24 hours
_AVAIL_CACHE_TTL_S = 60      # availability slot cache TTL


def _slot_key(dt: datetime) -> str:
    """Return a 15-minute-bucket UTC slot key for use in Redis lock names.

    Slots within the same 15-minute bucket share a lock key, reducing Redis
    key space while still serializing concurrent requests for the same resource.
    Example: 09:07 UTC → "20260615T0900", 09:16 UTC → "20260615T0915".
    """
    utc = dt.astimezone(timezone.utc)
    bucket_minute = (utc.minute // 15) * 15
    return utc.strftime(f"%Y%m%dT%H{bucket_minute:02d}")


def _within_hours(start: datetime, end: datetime, opening: str, closing: str, tz: str) -> bool:
    """Check that [start, end) falls entirely within dealership operating hours (local time)."""
    try:
        zone = zoneinfo.ZoneInfo(tz)
    except zoneinfo.ZoneInfoNotFoundError:
        return True  # graceful fallback if tz unknown

    open_h, open_m = map(int, opening.split(":"))
    close_h, close_m = map(int, closing.split(":"))
    open_time = time(open_h, open_m)
    close_time = time(close_h, close_m)

    local_start = start.astimezone(zone).time()
    local_end = end.astimezone(zone).time()
    # local_end of 00:00 means midnight — treat as closing
    if local_end == time(0, 0):
        local_end = time(23, 59, 59)
    return open_time <= local_start and local_end <= close_time


class BookingService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.appt_repo = AppointmentRepository(session)
        self.ref_repo = ReferenceRepository(session)

    async def create_appointment(
        self,
        payload: AppointmentCreate,
        customer_id: str,
        idempotency_key: str | None = None,
    ) -> Appointment:
        # ── 0. Idempotency check ────────────────────────────────────────
        if idempotency_key:
            cached_id = await get_redis().get(f"idem:{customer_id}:{idempotency_key}")
            if cached_id:
                cached = await self.appt_repo.get_by_id(cached_id)
                if cached:
                    return cached

        # Count this as a new request only after the idempotency cache miss
        appointments_requested.labels(
            dealership_id=payload.dealership_id,
            service_type_id=payload.service_type_id,
        ).inc()
        t0 = _time.monotonic()

        try:
            # ── 1. Validate references ──────────────────────────────────
            customer = await self.ref_repo.get_customer(customer_id)
            if not customer:
                raise NotFoundError("Customer")

            vehicle = await self.ref_repo.get_vehicle(payload.vehicle_id)
            if not vehicle:
                raise NotFoundError("Vehicle")
            if vehicle.customer_id != customer_id:
                raise ForbiddenError()

            dealership = await self.ref_repo.get_dealership(payload.dealership_id)
            if not dealership:
                raise NotFoundError("Dealership")

            service_type = await self.ref_repo.get_service_type(payload.service_type_id)
            if not service_type:
                raise NotFoundError("ServiceType")

            start = payload.scheduled_start
            end = start + timedelta(minutes=service_type.duration_minutes)

            # ── 2. Operating hours ──────────────────────────────────────
            if not _within_hours(start, end, dealership.opening_time, dealership.closing_time, dealership.timezone):
                raise SlotUnavailableError(
                    "Requested time is outside dealership operating hours.",
                    {"requested_start": start.isoformat(), "reason": "OUTSIDE_HOURS"},
                )

            # ── 3. Availability check (optimistic read) ─────────────────
            bay = await self.appt_repo.find_available_bay(payload.dealership_id, start, end)
            if not bay:
                raise SlotUnavailableError(
                    "No service bay is available for the requested time window.",
                    {"requested_start": start.isoformat(), "requested_end": end.isoformat(), "reason": "NO_BAY"},
                )

            tech = await self.appt_repo.find_available_technician(
                payload.dealership_id, start, end, service_type.required_skills
            )
            if not tech:
                raise SlotUnavailableError(
                    "No qualified technician is available for the requested time window.",
                    {"requested_start": start.isoformat(), "requested_end": end.isoformat(), "reason": "NO_TECHNICIAN"},
                )

            # ── 4. Distributed lock + DB transaction ────────────────────
            slot_key = _slot_key(start)

            async with acquire_slot_locks(bay.id, tech.id, slot_key):
                # Re-check inside transaction (defence-in-depth)
                if await self.appt_repo.has_bay_conflict(bay.id, start, end):
                    raise SlotUnavailableError(
                        "Service bay was taken by a concurrent request.",
                        {"reason": "NO_BAY"},
                    )
                if await self.appt_repo.has_technician_conflict(tech.id, start, end):
                    raise SlotUnavailableError(
                        "Technician was taken by a concurrent request.",
                        {"reason": "NO_TECHNICIAN"},
                    )

                appt = Appointment(
                    customer_id=customer_id,
                    vehicle_id=payload.vehicle_id,
                    dealership_id=payload.dealership_id,
                    service_type_id=payload.service_type_id,
                    service_bay_id=bay.id,
                    technician_id=tech.id,
                    scheduled_start=start,
                    scheduled_end=end,
                    status="CONFIRMED",
                )
                created = await self.appt_repo.create(appt)
                await self.session.commit()

            # ── 5. Post-commit side-effects ─────────────────────────────
            # Store idempotency key BEFORE publishing to SQS so that a crash
            # between commit and publish is handled correctly on retry.
            if idempotency_key:
                await get_redis().set(
                    f"idem:{customer_id}:{idempotency_key}",
                    created.id,
                    ex=_IDEMPOTENCY_TTL_S,
                )

            await publish_booking_confirmation(created.id)

            appointments_confirmed.labels(
                dealership_id=payload.dealership_id,
                service_type_id=payload.service_type_id,
            ).inc()
            booking_duration.labels(outcome="confirmed").observe(_time.monotonic() - t0)
            return created

        except (SlotUnavailableError, SlotTakenError) as exc:
            reason = exc.detail.get("error", {}).get("details", {}).get("reason", "UNAVAILABLE")
            appointments_rejected.labels(
                dealership_id=payload.dealership_id,
                reason=reason,
            ).inc()
            booking_duration.labels(outcome="rejected").observe(_time.monotonic() - t0)
            raise

    async def get_appointment(
        self,
        appointment_id: str,
        customer_id: str,
        role: str,
        dealership_id: str | None = None,
    ) -> Appointment:
        appt = await self.appt_repo.get_by_id(appointment_id)
        if not appt:
            raise NotFoundError("Appointment")
        if role == "CUSTOMER" and appt.customer_id != customer_id:
            raise ForbiddenError()
        if role == "STAFF" and appt.dealership_id != dealership_id:
            raise ForbiddenError()
        return appt

    async def cancel_appointment(self, appointment_id: str, customer_id: str) -> Appointment:
        appt = await self.appt_repo.get_by_id(appointment_id)
        if not appt:
            raise NotFoundError("Appointment")
        if appt.customer_id != customer_id:
            raise ForbiddenError()
        if appt.status != "CONFIRMED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {"code": "INVALID_STATE", "message": f"Cannot cancel an appointment with status {appt.status}.", "details": {}}},
            )
        now = datetime.now(timezone.utc)
        scheduled = appt.scheduled_start
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        if scheduled <= now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {"code": "PAST_APPOINTMENT", "message": "Cannot cancel a past appointment.", "details": {}}},
            )
        appt.status = "CANCELLED"
        appt.cancelled_at = now
        appt.updated_at = now
        await self.appt_repo.save(appt)
        await self.session.commit()
        return appt

    async def list_appointments(
        self,
        customer_id: str,
        status_filter: str | None,
        page: int,
        limit: int,
    ) -> tuple[list[Appointment], int]:
        return await self.appt_repo.list_for_customer(customer_id, status_filter, page, limit)

    async def check_availability(
        self,
        dealership_id: str,
        service_type_id: str,
        date_str: str,
    ) -> list[tuple[datetime, datetime]]:
        # ── Cache read (best-effort; Redis miss falls through to DB) ────
        redis = get_redis()
        cache_key = f"avail:{dealership_id}:{service_type_id}:{date_str}"
        try:
            cached = await redis.get(cache_key)
            if cached:
                return [
                    (datetime.fromisoformat(s), datetime.fromisoformat(e))
                    for s, e in json.loads(cached)
                ]
        except Exception:
            pass  # treat as cache miss; log is not worth the noise here

        t0 = _time.monotonic()
        try:
            dealership = await self.ref_repo.get_dealership(dealership_id)
            if not dealership:
                raise NotFoundError("Dealership")

            service_type = await self.ref_repo.get_service_type(service_type_id)
            if not service_type:
                raise NotFoundError("ServiceType")

            try:
                query_date = date_type.fromisoformat(date_str)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use YYYY-MM-DD.")

            try:
                zone = zoneinfo.ZoneInfo(dealership.timezone)
            except zoneinfo.ZoneInfoNotFoundError:
                zone = timezone.utc

            open_h, open_m = map(int, dealership.opening_time.split(":"))
            close_h, close_m = map(int, dealership.closing_time.split(":"))

            slot_dur = timedelta(minutes=service_type.duration_minutes)
            current = datetime(query_date.year, query_date.month, query_date.day, open_h, open_m, tzinfo=zone)
            closing = datetime(query_date.year, query_date.month, query_date.day, close_h, close_m, tzinfo=zone)

            # Fetch all resources and the day's appointments in 3 queries instead of
            # 2 × N queries (one per candidate slot).
            bays = await self.appt_repo.list_active_bays(dealership_id)
            techs = await self.appt_repo.list_active_technicians(dealership_id)

            # Filter technicians by skill in Python (keeps SQLite test compat)
            required = service_type.required_skills or []
            qualified_tech_ids = {
                t.id for t in techs
                if not required or all(s in (t.skills or []) for s in required)
            }

            if not bays or not qualified_tech_ids:
                return []

            bay_ids = {b.id for b in bays}

            # One query covering the whole operating day
            day_appointments = await self.appt_repo.list_confirmed_appointments_in_window(
                dealership_id,
                current.astimezone(timezone.utc),
                closing.astimezone(timezone.utc),
            )

            slots: list[tuple[datetime, datetime]] = []
            now = datetime.now(timezone.utc)

            def _to_utc(dt: datetime) -> datetime:
                """Ensure datetime is UTC-aware; SQLite returns naive datetimes."""
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)

            while current + slot_dur <= closing:
                slot_end = current + slot_dur
                start_utc = current.astimezone(timezone.utc)
                end_utc = slot_end.astimezone(timezone.utc)

                if start_utc > now:
                    # Which bays/techs are occupied during this slot?
                    occupied_bays = {
                        a.service_bay_id for a in day_appointments
                        if _to_utc(a.scheduled_start) < end_utc and _to_utc(a.scheduled_end) > start_utc
                    }
                    occupied_techs = {
                        a.technician_id for a in day_appointments
                        if _to_utc(a.scheduled_start) < end_utc and _to_utc(a.scheduled_end) > start_utc
                    }

                    free_bay = bay_ids - occupied_bays
                    free_tech = qualified_tech_ids - occupied_techs

                    if free_bay and free_tech:
                        slots.append((start_utc, end_utc))

                current += slot_dur
        finally:
            availability_query_duration.labels(dealership_id=dealership_id).observe(
                _time.monotonic() - t0
            )

        # ── Cache write (best-effort) ───────────────────────────────────
        try:
            await redis.set(
                cache_key,
                json.dumps([[s.isoformat(), e.isoformat()] for s, e in slots]),
                ex=_AVAIL_CACHE_TTL_S,
            )
        except Exception:
            pass

        return slots
