"""Integration tests — full HTTP request/response via FastAPI TestClient."""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
import app.models.models  # noqa
from app.models.models import Customer, Vehicle, Dealership, ServiceType, ServiceBay, Technician
from app.services.auth_service import hash_password


# ── App setup with overridden DB ───────────────────────────────────────────

@pytest_asyncio.fixture
async def app_with_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    from app.main import create_app
    app = create_app()

    async def override_get_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # Seed data
    async with Session() as session:
        d = Dealership(id="d-int-01", name="Integration Dealership", timezone="UTC", opening_time="08:00", closing_time="18:00")
        st = ServiceType(id="st-int-01", name="Oil Change", duration_minutes=60, required_skills=["oil"])
        bay = ServiceBay(id="bay-int-01", dealership_id="d-int-01", label="Bay 1")
        tech = Technician(id="tech-int-01", dealership_id="d-int-01", name="Alice", skills=["oil"])
        customer = Customer(id="cust-int-01", name="Jane", email="jane@inttest.com", password_hash=hash_password("Password123"))
        vehicle = Vehicle(id="veh-int-01", customer_id="cust-int-01", make="Toyota", model="Camry", year=2021)
        session.add_all([d, st, bay, tech, customer, vehicle])
        await session.commit()

    yield app, {
        "dealership_id": "d-int-01",
        "service_type_id": "st-int-01",
        "vehicle_id": "veh-int-01",
        "customer_id": "cust-int-01",
    }
    await engine.dispose()


@pytest_asyncio.fixture
async def client(app_with_db):
    app, seed = app_with_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, seed


async def _get_token(client, email="jane@inttest.com", password="Password123"):
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _future_start(hours: int = 24) -> str:
    dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=hours)
    return dt.isoformat()


# ── Auth endpoints ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_and_login(client):
    c, _ = client
    resp = await c.post("/api/v1/auth/register", json={
        "name": "New User", "email": "new@inttest.com", "password": "Secure1234"
    })
    assert resp.status_code == 201, resp.text

    resp = await c.post("/api/v1/auth/login", json={"email": "new@inttest.com", "password": "Secure1234"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_invalid_credentials(client):
    c, _ = client
    resp = await c.post("/api/v1/auth/login", json={"email": "jane@inttest.com", "password": "wrong"})
    assert resp.status_code == 401


# ── Booking endpoints ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_appointment_success(client):
    c, seed = client
    token = await _get_token(c)
    resp = await c.post("/api/v1/appointments", json={
        "vehicle_id": seed["vehicle_id"],
        "dealership_id": seed["dealership_id"],
        "service_type_id": seed["service_type_id"],
        "scheduled_start": _future_start(24),
    }, headers=_auth(token))
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "CONFIRMED"
    assert body["service_bay"]["id"] == "bay-int-01"
    assert body["technician"]["id"] == "tech-int-01"


@pytest.mark.asyncio
async def test_create_appointment_no_auth_returns_401(client):
    c, seed = client
    resp = await c.post("/api/v1/appointments", json={
        "vehicle_id": seed["vehicle_id"],
        "dealership_id": seed["dealership_id"],
        "service_type_id": seed["service_type_id"],
        "scheduled_start": _future_start(24),
    })
    assert resp.status_code in (401, 403)  # HTTPBearer raises 403 on some versions, 401 on others


@pytest.mark.asyncio
async def test_double_booking_returns_409(client):
    c, seed = client
    token = await _get_token(c)
    start = _future_start(48)
    payload = {
        "vehicle_id": seed["vehicle_id"],
        "dealership_id": seed["dealership_id"],
        "service_type_id": seed["service_type_id"],
        "scheduled_start": start,
    }
    r1 = await c.post("/api/v1/appointments", json=payload, headers=_auth(token))
    assert r1.status_code == 201

    r2 = await c.post("/api/v1/appointments", json=payload, headers=_auth(token))
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_get_appointment(client):
    c, seed = client
    token = await _get_token(c)
    create_resp = await c.post("/api/v1/appointments", json={
        "vehicle_id": seed["vehicle_id"],
        "dealership_id": seed["dealership_id"],
        "service_type_id": seed["service_type_id"],
        "scheduled_start": _future_start(72),
    }, headers=_auth(token))
    appt_id = create_resp.json()["id"]

    get_resp = await c.get(f"/api/v1/appointments/{appt_id}", headers=_auth(token))
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == appt_id


@pytest.mark.asyncio
async def test_cancel_appointment(client):
    c, seed = client
    token = await _get_token(c)
    create_resp = await c.post("/api/v1/appointments", json={
        "vehicle_id": seed["vehicle_id"],
        "dealership_id": seed["dealership_id"],
        "service_type_id": seed["service_type_id"],
        "scheduled_start": _future_start(96),
    }, headers=_auth(token))
    assert create_resp.status_code == 201
    appt_id = create_resp.json()["id"]

    cancel_resp = await c.patch(f"/api/v1/appointments/{appt_id}/cancel", headers=_auth(token))
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_list_appointments(client):
    c, seed = client
    token = await _get_token(c)
    await c.post("/api/v1/appointments", json={
        "vehicle_id": seed["vehicle_id"],
        "dealership_id": seed["dealership_id"],
        "service_type_id": seed["service_type_id"],
        "scheduled_start": _future_start(120),
    }, headers=_auth(token))

    resp = await c.get("/api/v1/appointments", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert body["pagination"]["total"] >= 1


@pytest.mark.asyncio
async def test_availability_endpoint(client):
    c, seed = client
    token = await _get_token(c)
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    resp = await c.get(
        f"/api/v1/availability?dealership_id={seed['dealership_id']}&service_type_id={seed['service_type_id']}&date={tomorrow}",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "slots" in body
    assert len(body["slots"]) > 0


@pytest.mark.asyncio
async def test_health_endpoint(client):
    c, _ = client
    resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
