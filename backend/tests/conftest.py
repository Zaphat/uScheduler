"""Shared pytest fixtures for the uScheduler test suite.

Unit tests run entirely in-process using SQLite (aiosqlite) + fakeredis.
No real PostgreSQL or Redis connection is required.
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

# ── Patch settings BEFORE any app import ──────────────────────────────────
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-bytes-long-xx")
os.environ.setdefault("TESTING", "true")

from app.db.session import Base
import app.models.models  # ensure models are registered on Base.metadata
from app.models.models import Customer, Vehicle, Dealership, ServiceType, ServiceBay, Technician
from app.services.auth_service import hash_password
from app.core.locks import set_redis


# ── In-memory SQLite engine ────────────────────────────────────────────────

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    Session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with Session() as session:
        yield session


# ── Fake Redis ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fake_redis():
    import fakeredis.aioredis as fakeredis
    client = fakeredis.FakeRedis(decode_responses=True)
    set_redis(client)
    yield client


# ── Seed helpers ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def seed_data(db_session: AsyncSession):
    """Insert minimal seed data and return IDs for use in tests."""
    d = Dealership(
        id="d-test-01",
        name="Test Dealership",
        timezone="UTC",
        opening_time="08:00",
        closing_time="18:00",
    )
    st = ServiceType(
        id="st-oil-01",
        name="Oil Change",
        duration_minutes=60,
        required_skills=["oil"],
    )
    bay = ServiceBay(id="bay-01", dealership_id="d-test-01", label="Bay 1")
    tech = Technician(id="tech-01", dealership_id="d-test-01", name="Alice", skills=["oil", "tyres"])
    customer = Customer(
        id="cust-01",
        name="Test User",
        email="test@example.com",
        password_hash=hash_password("Password123"),
    )
    vehicle = Vehicle(id="veh-01", customer_id="cust-01", make="Toyota", model="Camry", year=2021)

    db_session.add_all([d, st, bay, tech, customer, vehicle])
    await db_session.commit()

    return {
        "dealership_id": d.id,
        "service_type_id": st.id,
        "bay_id": bay.id,
        "tech_id": tech.id,
        "customer_id": customer.id,
        "vehicle_id": vehicle.id,
    }


def future_dt(hours_from_now: int = 24) -> datetime:
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=hours_from_now)
