"""Unit tests for booking service business logic."""
import pytest
from datetime import datetime, timezone, timedelta

from tests.conftest import future_dt
from app.services.booking_service import _within_hours, _slot_key, BookingService
from app.schemas.schemas import AppointmentCreate
from app.core.exceptions import SlotUnavailableError, ForbiddenError, NotFoundError


# ── _within_hours ──────────────────────────────────────────────────────────

class TestWithinHours:
    def test_within_hours_returns_true(self):
        dt = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
        end = dt + timedelta(hours=1)
        assert _within_hours(dt, end, "08:00", "18:00", "UTC") is True

    def test_before_opening_returns_false(self):
        dt = datetime(2026, 6, 15, 7, 0, tzinfo=timezone.utc)
        end = dt + timedelta(hours=1)
        assert _within_hours(dt, end, "08:00", "18:00", "UTC") is False

    def test_at_closing_returns_false(self):
        # start at 18:00, end at 19:00 — end exceeds closing
        dt = datetime(2026, 6, 15, 18, 0, tzinfo=timezone.utc)
        end = dt + timedelta(hours=1)
        assert _within_hours(dt, end, "08:00", "18:00", "UTC") is False

    def test_exactly_at_opening_returns_true(self):
        dt = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)
        end = dt + timedelta(hours=1)
        assert _within_hours(dt, end, "08:00", "18:00", "UTC") is True

    def test_end_exceeds_closing_returns_false(self):
        # start OK but end time crosses closing
        dt = datetime(2026, 6, 15, 17, 30, tzinfo=timezone.utc)
        end = dt + timedelta(hours=1)  # end = 18:30, closing = 18:00
        assert _within_hours(dt, end, "08:00", "18:00", "UTC") is False

    def test_unknown_timezone_returns_true(self):
        dt = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
        end = dt + timedelta(hours=1)
        assert _within_hours(dt, end, "08:00", "18:00", "Not/ATimezone") is True


# ── _slot_key ──────────────────────────────────────────────────────────────

class TestSlotKey:
    def test_same_datetime_produces_same_key(self):
        t = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)
        assert _slot_key(t) == _slot_key(t)

    def test_same_15min_bucket_produces_same_key(self):
        # 09:00 and 09:07 both fall in the 09:00 bucket
        t1 = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 6, 15, 9, 7, tzinfo=timezone.utc)
        assert _slot_key(t1) == _slot_key(t2)

    def test_different_bucket_produces_different_key(self):
        # 09:00 → bucket 09:00; 09:15 → bucket 09:15
        t1 = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 6, 15, 9, 15, tzinfo=timezone.utc)
        assert _slot_key(t1) != _slot_key(t2)

    def test_key_format_is_utc_15min_bucket_precision(self):
        t = datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc)
        assert _slot_key(t) == "20260615T0930"


# ── AppointmentCreate validator ────────────────────────────────────────────

class TestAppointmentCreateValidator:
    def test_past_datetime_raises(self):
        from pydantic import ValidationError
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        with pytest.raises(ValidationError, match="future"):
            AppointmentCreate(
                vehicle_id="v1",
                dealership_id="d1",
                service_type_id="s1",
                scheduled_start=past,
            )

    def test_naive_datetime_raises(self):
        from pydantic import ValidationError
        naive = datetime(2099, 1, 1, 10, 0)  # no tzinfo
        with pytest.raises(ValidationError, match="timezone"):
            AppointmentCreate(
                vehicle_id="v1",
                dealership_id="d1",
                service_type_id="s1",
                scheduled_start=naive,
            )

    def test_valid_future_datetime_passes(self):
        future = datetime(2099, 1, 1, 10, 0, tzinfo=timezone.utc)
        payload = AppointmentCreate(
            vehicle_id="v1",
            dealership_id="d1",
            service_type_id="s1",
            scheduled_start=future,
        )
        assert payload.scheduled_start == future


# ── BookingService (with DB) ───────────────────────────────────────────────

@pytest.mark.asyncio
class TestBookingServiceCreate:
    async def test_successful_booking(self, db_session, seed_data):
        service = BookingService(db_session)
        payload = AppointmentCreate(
            vehicle_id=seed_data["vehicle_id"],
            dealership_id=seed_data["dealership_id"],
            service_type_id=seed_data["service_type_id"],
            scheduled_start=future_dt(24),
        )
        appt = await service.create_appointment(payload, customer_id=seed_data["customer_id"])
        assert appt.status == "CONFIRMED"
        assert appt.service_bay_id == seed_data["bay_id"]
        assert appt.technician_id == seed_data["tech_id"]
        assert appt.scheduled_end > appt.scheduled_start

    async def test_wrong_vehicle_owner_raises_forbidden(self, db_session, seed_data):
        service = BookingService(db_session)
        # create a second customer who does not own the vehicle
        from app.models.models import Customer
        from app.services.auth_service import hash_password
        other = Customer(id="cust-02", name="Other", email="other@example.com", password_hash=hash_password("pw"))
        db_session.add(other)
        await db_session.commit()

        payload = AppointmentCreate(
            vehicle_id=seed_data["vehicle_id"],
            dealership_id=seed_data["dealership_id"],
            service_type_id=seed_data["service_type_id"],
            scheduled_start=future_dt(48),
        )
        with pytest.raises(ForbiddenError):
            await service.create_appointment(payload, customer_id="cust-02")

    async def test_invalid_dealership_raises_not_found(self, db_session, seed_data):
        service = BookingService(db_session)
        payload = AppointmentCreate(
            vehicle_id=seed_data["vehicle_id"],
            dealership_id="nonexistent-dealership",
            service_type_id=seed_data["service_type_id"],
            scheduled_start=future_dt(24),
        )
        with pytest.raises(NotFoundError):
            await service.create_appointment(payload, customer_id=seed_data["customer_id"])

    async def test_outside_operating_hours_raises_slot_unavailable(self, db_session, seed_data):
        service = BookingService(db_session)
        # 02:00 UTC is outside 08:00–18:00 UTC
        early = datetime(2099, 6, 15, 2, 0, tzinfo=timezone.utc)
        payload = AppointmentCreate(
            vehicle_id=seed_data["vehicle_id"],
            dealership_id=seed_data["dealership_id"],
            service_type_id=seed_data["service_type_id"],
            scheduled_start=early,
        )
        with pytest.raises(SlotUnavailableError):
            await service.create_appointment(payload, customer_id=seed_data["customer_id"])

    async def test_double_booking_same_slot_raises_slot_unavailable(self, db_session, seed_data):
        """Second booking for the same slot is rejected (bay already taken)."""
        service = BookingService(db_session)
        start = future_dt(72)
        payload = AppointmentCreate(
            vehicle_id=seed_data["vehicle_id"],
            dealership_id=seed_data["dealership_id"],
            service_type_id=seed_data["service_type_id"],
            scheduled_start=start,
        )
        # First booking succeeds
        await service.create_appointment(payload, customer_id=seed_data["customer_id"])

        # Second booking for same slot: bay is taken
        with pytest.raises(SlotUnavailableError):
            await service.create_appointment(payload, customer_id=seed_data["customer_id"])

    async def test_no_qualified_technician_raises_slot_unavailable(self, db_session, seed_data):
        """Booking is rejected when the only technician lacks required skills."""
        from app.models.models import ServiceType
        # Create a service type requiring skills the existing tech doesn't have
        advanced = ServiceType(
            id="st-engine-01",
            name="Engine Overhaul",
            duration_minutes=60,
            required_skills=["engine", "electrical"],
            dealership_id=seed_data["dealership_id"],
        )
        db_session.add(advanced)
        await db_session.commit()

        service = BookingService(db_session)
        payload = AppointmentCreate(
            vehicle_id=seed_data["vehicle_id"],
            dealership_id=seed_data["dealership_id"],
            service_type_id="st-engine-01",
            scheduled_start=future_dt(200),
        )
        with pytest.raises(SlotUnavailableError, match="qualified technician"):
            await service.create_appointment(payload, customer_id=seed_data["customer_id"])

    async def test_service_type_scoped_to_other_dealership_raises_not_found(self, db_session, seed_data):
        """Booking is rejected when the service type belongs to a different dealership."""
        from app.models.models import Dealership, ServiceType
        other = Dealership(id="d-other-01", name="Other Dealership", timezone="UTC", opening_time="08:00", closing_time="18:00")
        scoped = ServiceType(
            id="st-other-01",
            name="Detailing",
            duration_minutes=60,
            required_skills=[],
            dealership_id="d-other-01",
        )
        db_session.add_all([other, scoped])
        await db_session.commit()

        service = BookingService(db_session)
        payload = AppointmentCreate(
            vehicle_id=seed_data["vehicle_id"],
            dealership_id=seed_data["dealership_id"],
            service_type_id="st-other-01",
            scheduled_start=future_dt(224),
        )
        with pytest.raises(NotFoundError):
            await service.create_appointment(payload, customer_id=seed_data["customer_id"])


@pytest.mark.asyncio
class TestBookingServiceCancel:
    async def test_cancel_confirmed_appointment(self, db_session, seed_data):
        service = BookingService(db_session)
        payload = AppointmentCreate(
            vehicle_id=seed_data["vehicle_id"],
            dealership_id=seed_data["dealership_id"],
            service_type_id=seed_data["service_type_id"],
            scheduled_start=future_dt(96),
        )
        appt = await service.create_appointment(payload, customer_id=seed_data["customer_id"])
        cancelled = await service.cancel_appointment(appt.id, seed_data["customer_id"])
        assert cancelled.status == "CANCELLED"
        assert cancelled.cancelled_at is not None

    async def test_cancel_wrong_customer_raises_forbidden(self, db_session, seed_data):
        service = BookingService(db_session)
        payload = AppointmentCreate(
            vehicle_id=seed_data["vehicle_id"],
            dealership_id=seed_data["dealership_id"],
            service_type_id=seed_data["service_type_id"],
            scheduled_start=future_dt(120),
        )
        appt = await service.create_appointment(payload, customer_id=seed_data["customer_id"])
        with pytest.raises(ForbiddenError):
            await service.cancel_appointment(appt.id, "other-customer")

    async def test_cancel_already_cancelled_raises_conflict(self, db_session, seed_data):
        from fastapi import HTTPException
        service = BookingService(db_session)
        payload = AppointmentCreate(
            vehicle_id=seed_data["vehicle_id"],
            dealership_id=seed_data["dealership_id"],
            service_type_id=seed_data["service_type_id"],
            scheduled_start=future_dt(144),
        )
        appt = await service.create_appointment(payload, customer_id=seed_data["customer_id"])
        await service.cancel_appointment(appt.id, seed_data["customer_id"])
        with pytest.raises(HTTPException) as exc_info:
            await service.cancel_appointment(appt.id, seed_data["customer_id"])
        assert exc_info.value.status_code == 400


@pytest.mark.asyncio
class TestAvailabilityCheck:
    async def test_returns_slots_within_hours(self, db_session, seed_data):
        from datetime import date
        service = BookingService(db_session)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
        slots = await service.check_availability(
            seed_data["dealership_id"],
            seed_data["service_type_id"],
            tomorrow,
        )
        assert len(slots) > 0
        for start, end in slots:
            assert end > start

    async def test_no_slots_when_bay_fully_booked(self, db_session, seed_data):
        """Book every possible slot for the day — availability should return empty."""
        service = BookingService(db_session)
        # The dealership has 1 bay and 1 technician; oil change = 60 min; 08:00–18:00 = 10 slots
        target_date = datetime(2099, 8, 1, tzinfo=timezone.utc)
        for hour in range(8, 18):
            start = target_date.replace(hour=hour)
            payload = AppointmentCreate(
                vehicle_id=seed_data["vehicle_id"],
                dealership_id=seed_data["dealership_id"],
                service_type_id=seed_data["service_type_id"],
                scheduled_start=start,
            )
            try:
                await service.create_appointment(payload, customer_id=seed_data["customer_id"])
            except Exception:
                pass  # Some may fail if resources exhausted

        slots = await service.check_availability(
            seed_data["dealership_id"],
            seed_data["service_type_id"],
            "2099-08-01",
        )
        assert slots == []
