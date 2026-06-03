from datetime import datetime
from sqlalchemy import func, select, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import (
    Appointment, ServiceBay, Technician, ServiceType, Dealership, Customer, Vehicle
)


class AppointmentRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Availability helpers ───────────────────────────────────────────────

    async def find_available_bay(
        self,
        dealership_id: str,
        start: datetime,
        end: datetime,
    ) -> ServiceBay | None:
        conflict = (
            select(Appointment.id)
            .where(
                Appointment.service_bay_id == ServiceBay.id,
                Appointment.status == "CONFIRMED",
                Appointment.scheduled_start < end,
                Appointment.scheduled_end > start,
            )
        )
        stmt = (
            select(ServiceBay)
            .where(
                ServiceBay.dealership_id == dealership_id,
                ServiceBay.is_active.is_(True),
                ~exists(conflict),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_qualified_technician(
        self,
        dealership_id: str,
        start: datetime,
        end: datetime,
        required_skills: list[str],
    ) -> Technician | None:
        """Find a technician who is both qualified and available."""
        conflict = (
            select(Appointment.id)
            .where(
                Appointment.technician_id == Technician.id,
                Appointment.status == "CONFIRMED",
                Appointment.scheduled_start < end,
                Appointment.scheduled_end > start,
            )
        )
        # Fetch active technicians without conflicts; filter skills in Python
        # (JSON columns don't support the @> operator in SQLite used for tests)
        stmt = (
            select(Technician)
            .where(
                Technician.dealership_id == dealership_id,
                Technician.is_active.is_(True),
                ~exists(conflict),
            )
        )
        result = await self.session.execute(stmt)
        for tech in result.scalars():
            if not required_skills or all(s in (tech.skills or []) for s in required_skills):
                return tech
        return None

    async def has_bay_conflict(self, bay_id: str, start: datetime, end: datetime, exclude_id: str | None = None) -> bool:
        stmt = select(Appointment.id).where(
            Appointment.service_bay_id == bay_id,
            Appointment.status == "CONFIRMED",
            Appointment.scheduled_start < end,
            Appointment.scheduled_end > start,
        )
        if exclude_id:
            stmt = stmt.where(Appointment.id != exclude_id)
        result = await self.session.execute(stmt.limit(1))
        return result.scalar_one_or_none() is not None

    async def has_technician_conflict(self, tech_id: str, start: datetime, end: datetime, exclude_id: str | None = None) -> bool:
        stmt = select(Appointment.id).where(
            Appointment.technician_id == tech_id,
            Appointment.status == "CONFIRMED",
            Appointment.scheduled_start < end,
            Appointment.scheduled_end > start,
        )
        if exclude_id:
            stmt = stmt.where(Appointment.id != exclude_id)
        result = await self.session.execute(stmt.limit(1))
        return result.scalar_one_or_none() is not None

    # ── CRUD ──────────────────────────────────────────────────────────────

    async def create(self, appt: Appointment) -> Appointment:
        self.session.add(appt)
        await self.session.flush()  # get id without committing
        await self.session.refresh(appt, ["service_type", "service_bay", "technician"])
        return appt

    async def get_by_id(self, appointment_id: str) -> Appointment | None:
        stmt = (
            select(Appointment)
            .options(
                selectinload(Appointment.service_type),
                selectinload(Appointment.service_bay),
                selectinload(Appointment.technician),
            )
            .where(Appointment.id == appointment_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_customer(
        self,
        customer_id: str,
        status_filter: str | None,
        page: int,
        limit: int,
    ) -> tuple[list[Appointment], int]:
        base = select(Appointment).options(
            selectinload(Appointment.service_type),
            selectinload(Appointment.service_bay),
            selectinload(Appointment.technician),
        ).where(Appointment.customer_id == customer_id)

        if status_filter:
            base = base.where(Appointment.status == status_filter.upper())

        count_q = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_q)).scalar_one()

        data_q = base.order_by(Appointment.scheduled_start.desc()).offset((page - 1) * limit).limit(limit)
        rows = (await self.session.execute(data_q)).scalars().all()
        return list(rows), total

    async def save(self, appt: Appointment) -> Appointment:
        await self.session.flush()
        return appt

    # ── Batched availability helpers (used by check_availability) ─────────

    async def list_active_bays(self, dealership_id: str) -> list[ServiceBay]:
        result = await self.session.execute(
            select(ServiceBay).where(
                ServiceBay.dealership_id == dealership_id,
                ServiceBay.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def list_active_technicians(self, dealership_id: str) -> list[Technician]:
        result = await self.session.execute(
            select(Technician).where(
                Technician.dealership_id == dealership_id,
                Technician.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def list_confirmed_appointments_in_window(
        self,
        dealership_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[Appointment]:
        """Return all CONFIRMED appointments for a dealership that overlap [window_start, window_end)."""
        result = await self.session.execute(
            select(Appointment).where(
                Appointment.dealership_id == dealership_id,
                Appointment.status == "CONFIRMED",
                Appointment.scheduled_start < window_end,
                Appointment.scheduled_end > window_start,
            )
        )
        return list(result.scalars().all())


class ReferenceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_customer(self, customer_id: str) -> Customer | None:
        return await self.session.get(Customer, customer_id)

    async def get_vehicle(self, vehicle_id: str) -> Vehicle | None:
        return await self.session.get(Vehicle, vehicle_id)

    async def get_dealership(self, dealership_id: str) -> Dealership | None:
        return await self.session.get(Dealership, dealership_id)

    async def get_service_type(self, service_type_id: str) -> ServiceType | None:
        return await self.session.get(ServiceType, service_type_id)

    async def list_dealerships(self) -> list[Dealership]:
        result = await self.session.execute(select(Dealership))
        return list(result.scalars().all())

    async def list_service_types_for_dealership(self, dealership_id: str) -> list[ServiceType]:
        result = await self.session.execute(
            select(ServiceType).where(ServiceType.dealership_id == dealership_id)
        )
        return list(result.scalars().all())
