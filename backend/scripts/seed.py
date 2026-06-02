"""Seed the database with demo data for local development and testing.

Run from the backend/ directory:
    python -m scripts.seed
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings
from app.models.models import Customer, Vehicle, Dealership, ServiceType, ServiceBay, Technician
from app.services.auth_service import hash_password

_engine = create_async_engine(settings.DATABASE_URL, echo=False)
_Session = async_sessionmaker(_engine, expire_on_commit=False)


async def seed():
    async with _Session() as session:
        # Dealership
        d = Dealership(
            id="d0000000-0000-0000-0000-000000000001",
            name="Sunrise Auto Service",
            address="123 Main St, Springfield",
            timezone="America/New_York",
            opening_time="08:00",
            closing_time="18:00",
        )
        session.add(d)

        # Service Types
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
            description="Rotate all four tyres.",
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

        # Service Bays
        bays = [
            ServiceBay(id=f"b000000{i}-0000-0000-0000-000000000001", dealership_id=d.id, label=f"Bay {i}")
            for i in range(1, 4)
        ]
        session.add_all(bays)

        # Technicians
        techs = [
            Technician(id="t0000000-0000-0000-0000-000000000001", dealership_id=d.id, name="Alex Rivera", skills=["oil", "tyres", "engine", "electrical"]),
            Technician(id="t0000000-0000-0000-0000-000000000002", dealership_id=d.id, name="Sam Chen", skills=["oil", "tyres"]),
            Technician(id="t0000000-0000-0000-0000-000000000003", dealership_id=d.id, name="Jordan Lee", skills=["engine", "electrical"]),
        ]
        session.add_all(techs)

        # Demo customer
        customer = Customer(
            id="c0000000-0000-0000-0000-000000000001",
            name="Jane Smith",
            email="jane@example.com",
            phone="+12125550100",
            password_hash=hash_password("Password123"),
        )
        session.add(customer)

        vehicle = Vehicle(
            id="v0000000-0000-0000-0000-000000000001",
            customer_id=customer.id,
            make="Toyota",
            model="Camry",
            year=2021,
            vin="1HGBH41JXMN109186",
            license_plate="ABC-1234",
        )
        session.add(vehicle)

        await session.commit()
        print("✓ Seed data inserted.")
        print(f"  Customer email : jane@example.com")
        print(f"  Password       : Password123")
        print(f"  Dealership ID  : {d.id}")
        print(f"  Oil Change ID  : {oil.id}")
        print(f"  Vehicle ID     : {vehicle.id}")


if __name__ == "__main__":
    asyncio.run(seed())
