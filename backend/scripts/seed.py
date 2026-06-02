"""Seed the database with demo data for local development and testing.

Run from the backend/ directory:
    python -m scripts.seed

Seeded entities
---------------
Dealership  : Sunrise Auto Service       d0000000-0000-0000-0000-000000000001
Service Types:
  Oil Change (60 min)                   s0000000-0000-0000-0000-000000000001
  Tyre Rotation (45 min)                s0000000-0000-0000-0000-000000000002
  Engine Overhaul (240 min)             s0000000-0000-0000-0000-000000000003
Service Bays: Bay 1-3                   b0000001-… / b0000002-… / b0000003-…
Technicians:
  Alex Rivera (oil, tyres, engine, electrical)  t0000000-0000-0000-0000-000000000001
  Sam Chen    (oil, tyres)                      t0000000-0000-0000-0000-000000000002
  Jordan Lee  (engine, electrical)              t0000000-0000-0000-0000-000000000003
Customers:
  Jane Smith  jane@example.com / Password123    c0000000-0000-0000-0000-000000000001
  John Doe    john@example.com / Password123    c0000000-0000-0000-0000-000000000002
Vehicles:
  2021 Toyota Camry  (Jane)                     v0000000-0000-0000-0000-000000000001
  2020 Honda Civic   (John)                     v0000000-0000-0000-0000-000000000002
Pre-seeded appointments (both CONFIRMED, 2026-06-20):
  a0000000-0000-0000-0000-000000000001  Jane / Camry     / Oil Change     09:00–10:00 UTC
  a0000000-0000-0000-0000-000000000002  John / Civic     / Tyre Rotation  10:00–10:45 UTC
  a0000000-0000-0000-0000-000000000003  Jane / Camry     / Engine Overhaul 13:00–17:00 UTC
"""
import asyncio
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings
from app.models.models import Appointment, Customer, Vehicle, Dealership, ServiceType, ServiceBay, Technician
from app.services.auth_service import hash_password

_engine = create_async_engine(settings.DATABASE_URL, echo=False)
_Session = async_sessionmaker(_engine, expire_on_commit=False)


def _dt(date_str: str) -> datetime:
    """Parse an ISO-8601 UTC string into an aware datetime."""
    return datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)


async def seed():
    async with _Session() as session:
        # Skip if already seeded (idempotent — safe to call on every container start).
        existing = await session.scalar(
            select(Dealership).where(Dealership.id == "d0000000-0000-0000-0000-000000000001")
        )
        if existing:
            print(" Seed data already present, skipping.")
            return

        # ── Dealership ────────────────────────────────────────────────────────
        d = Dealership(
            id="d0000000-0000-0000-0000-000000000001",
            name="Sunrise Auto Service",
            address="123 Main St, Springfield",
            timezone="America/New_York",
            opening_time="08:00",
            closing_time="18:00",
        )
        session.add(d)

        # ── Service Types ─────────────────────────────────────────────────────
        oil = ServiceType(
            id="s0000000-0000-0000-0000-000000000001",
            name="Oil Change",
            description="Full synthetic oil change with filter replacement.",
            duration_minutes=60,
            required_skills=["oil"],
            dealership_id=d.id,
        )
        tyre = ServiceType(
            id="s0000000-0000-0000-0000-000000000002",
            name="Tyre Rotation",
            description="Rotate all four tyres for even wear.",
            duration_minutes=45,
            required_skills=["tyres"],
            dealership_id=d.id,
        )
        engine_svc = ServiceType(
            id="s0000000-0000-0000-0000-000000000003",
            name="Engine Overhaul",
            description="Full engine inspection and overhaul.",
            duration_minutes=240,
            required_skills=["engine", "electrical"],
            dealership_id=d.id,
        )
        session.add_all([oil, tyre, engine_svc])

        # ── Service Bays ──────────────────────────────────────────────────────
        bay1 = ServiceBay(id="b0000001-0000-0000-0000-000000000001", dealership_id=d.id, label="Bay 1")
        bay2 = ServiceBay(id="b0000002-0000-0000-0000-000000000001", dealership_id=d.id, label="Bay 2")
        bay3 = ServiceBay(id="b0000003-0000-0000-0000-000000000001", dealership_id=d.id, label="Bay 3")
        session.add_all([bay1, bay2, bay3])

        # ── Technicians ───────────────────────────────────────────────────────
        alex   = Technician(id="t0000000-0000-0000-0000-000000000001", dealership_id=d.id, name="Alex Rivera", skills=["oil", "tyres", "engine", "electrical"])
        sam    = Technician(id="t0000000-0000-0000-0000-000000000002", dealership_id=d.id, name="Sam Chen",    skills=["oil", "tyres"])
        jordan = Technician(id="t0000000-0000-0000-0000-000000000003", dealership_id=d.id, name="Jordan Lee",  skills=["engine", "electrical"])
        session.add_all([alex, sam, jordan])

        # ── Customers ─────────────────────────────────────────────────────────
        jane = Customer(
            id="c0000000-0000-0000-0000-000000000001",
            name="Jane Smith",
            email="jane@example.com",
            phone="+12125550100",
            password_hash=hash_password("Password123"),
        )
        john = Customer(
            id="c0000000-0000-0000-0000-000000000002",
            name="John Doe",
            email="john@example.com",
            phone="+12125550199",
            password_hash=hash_password("Password123"),
        )
        session.add_all([jane, john])

        # ── Vehicles ──────────────────────────────────────────────────────────
        camry = Vehicle(
            id="v0000000-0000-0000-0000-000000000001",
            customer_id=jane.id,
            make="Toyota",
            model="Camry",
            year=2021,
            vin="1HGBH41JXMN109186",
            license_plate="ABC-1234",
        )
        civic = Vehicle(
            id="v0000000-0000-0000-0000-000000000002",
            customer_id=john.id,
            make="Honda",
            model="Civic",
            year=2020,
            vin="2HGFC2F59LH541234",
            license_plate="XYZ-5678",
        )
        session.add_all([camry, civic])

        # ── Pre-seeded Appointments ───────────────────────────────────────────
        # These let you immediately test GET /appointments and cancel endpoints.
        appt1 = Appointment(
            id="a0000000-0000-0000-0000-000000000001",
            customer_id=jane.id,
            vehicle_id=camry.id,
            dealership_id=d.id,
            service_type_id=oil.id,
            service_bay_id=bay1.id,
            technician_id=alex.id,
            scheduled_start=_dt("2026-06-20T13:00:00"),
            scheduled_end=_dt("2026-06-20T14:00:00"),
            status="CONFIRMED",
        )
        appt2 = Appointment(
            id="a0000000-0000-0000-0000-000000000002",
            customer_id=john.id,
            vehicle_id=civic.id,
            dealership_id=d.id,
            service_type_id=tyre.id,
            service_bay_id=bay2.id,
            technician_id=sam.id,
            scheduled_start=_dt("2026-06-20T14:00:00"),
            scheduled_end=_dt("2026-06-20T14:45:00"),
            status="CONFIRMED",
        )
        appt3 = Appointment(
            id="a0000000-0000-0000-0000-000000000003",
            customer_id=jane.id,
            vehicle_id=camry.id,
            dealership_id=d.id,
            service_type_id=engine_svc.id,
            service_bay_id=bay3.id,
            technician_id=jordan.id,
            scheduled_start=_dt("2026-06-20T17:00:00"),
            scheduled_end=_dt("2026-06-20T21:00:00"),
            status="CONFIRMED",
        )
        session.add_all([appt1, appt2, appt3])

        await session.commit()

    print(" Seed data inserted.")
    print()
    print("  ── Customers ───────────────────────────────────────────────────")
    print("  Jane Smith  jane@example.com / Password123")
    print("              id: c0000000-0000-0000-0000-000000000001")
    print("              vehicle (Camry): v0000000-0000-0000-0000-000000000001")
    print()
    print("  John Doe    john@example.com / Password123")
    print("              id: c0000000-0000-0000-0000-000000000002")
    print("              vehicle (Civic): v0000000-0000-0000-0000-000000000002")
    print()
    print("  ── Dealership ──────────────────────────────────────────────────")
    print("  Sunrise Auto Service")
    print("              id: d0000000-0000-0000-0000-000000000001")
    print()
    print("  ── Pre-seeded Appointments (2026-06-20, times in UTC / EDT=UTC-4) ──")
    print("  a0000000-…-001  Jane / Camry     / Oil Change      13:00–14:00 UTC (09:00–10:00 EDT)")
    print("  a0000000-…-002  John / Civic     / Tyre Rotation   14:00–14:45 UTC (10:00–10:45 EDT)")
    print("  a0000000-…-003  Jane / Camry     / Engine Overhaul 17:00–21:00 UTC (13:00–17:00 EDT)")


if __name__ == "__main__":
    asyncio.run(seed())
