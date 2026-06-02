"""Core booking service — orchestrates availability check, locking, and DB write."""
import zoneinfo
from datetime import datetime, time, timezone, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SlotUnavailableError, NotFoundError, ForbiddenError
from app.core.locks import acquire_slot_locks
from app.models.models import Appointment
from app.repositories.appointment_repo import AppointmentRepository, ReferenceRepository
from app.schemas.schemas import AppointmentCreate


def _slot_key(dt: datetime) -> str:
    """Bucket start time to 15-min granularity for lock key."""
    bucket = int(dt.timestamp() // (15 * 60))
    return str(bucket)


def _within_hours(dt: datetime, opening: str, closing: str, tz: str) -> bool:
    """Check that dt falls within dealership operating hours (local time)."""
    try:
        zone = zoneinfo.ZoneInfo(tz)
    except zoneinfo.ZoneInfoNotFoundError:
        return True  # graceful fallback if tz unknown

    local = dt.astimezone(zone)
    local_time = local.time()

    open_h, open_m = map(int, opening.split(":"))
    close_h, close_m = map(int, closing.split(":"))
    return time(open_h, open_m) <= local_time < time(close_h, close_m)


class BookingService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.appt_repo = AppointmentRepository(session)
        self.ref_repo = ReferenceRepository(session)

    async def create_appointment(
        self,
        payload: AppointmentCreate,
        customer_id: str,
    ) -> Appointment:
        # ── 1. Validate references ──────────────────────────────────────
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

        # ── 2. Operating hours ──────────────────────────────────────────
        if not _within_hours(start, dealership.opening_time, dealership.closing_time, dealership.timezone):
            raise SlotUnavailableError(
                "Requested time is outside dealership operating hours.",
                {"requested_start": start.isoformat()},
            )

        # ── 3. Availability check (optimistic read) ─────────────────────
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

        # ── 4. Distributed lock + DB transaction ────────────────────────
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

        return created

    async def get_appointment(self, appointment_id: str, customer_id: str, role: str) -> Appointment:
        appt = await self.appt_repo.get_by_id(appointment_id)
        if not appt:
            raise NotFoundError("Appointment")
        if role == "CUSTOMER" and appt.customer_id != customer_id:
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
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": {"code": "INVALID_STATE", "message": f"Cannot cancel an appointment with status {appt.status}.", "details": {}}},
            )
        now = datetime.now(timezone.utc)
        scheduled = appt.scheduled_start
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        if scheduled <= now:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
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
        from datetime import date as date_type

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

        slots: list[tuple[datetime, datetime]] = []
        now = datetime.now(timezone.utc)

        while current + slot_dur <= closing:
            slot_end = current + slot_dur
            start_utc = current.astimezone(timezone.utc)
            end_utc = slot_end.astimezone(timezone.utc)

            if start_utc > now:
                bay = await self.appt_repo.find_available_bay(dealership_id, start_utc, end_utc)
                if bay:
                    tech = await self.appt_repo.find_available_technician(
                        dealership_id, start_utc, end_utc, service_type.required_skills
                    )
                    if tech:
                        slots.append((start_utc, end_utc))
            current += slot_dur

        return slots
