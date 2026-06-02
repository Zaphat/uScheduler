from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr, Field, field_validator
import uuid


# ── Auth ──────────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ── Customer ──────────────────────────────────────────────────────────────────

class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = None
    password: str = Field(min_length=8)


class CustomerOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    name: str
    email: str
    phone: str | None
    created_at: datetime


# ── Vehicle ───────────────────────────────────────────────────────────────────

class VehicleCreate(BaseModel):
    make: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=50)
    year: int = Field(ge=1900, le=2100)
    vin: str | None = Field(default=None, min_length=17, max_length=17)
    license_plate: str | None = None


class VehicleOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    customer_id: str
    make: str
    model: str
    year: int
    vin: str | None
    license_plate: str | None


# ── Dealership ────────────────────────────────────────────────────────────────

class DealershipOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    name: str
    address: str | None
    timezone: str
    opening_time: str
    closing_time: str


# ── ServiceType ───────────────────────────────────────────────────────────────

class ServiceTypeOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    name: str
    description: str | None
    duration_minutes: int
    required_skills: list[str]


# ── Appointments ──────────────────────────────────────────────────────────────

class AppointmentCreate(BaseModel):
    vehicle_id: str
    dealership_id: str
    service_type_id: str
    scheduled_start: datetime

    @field_validator("scheduled_start")
    @classmethod
    def must_be_future(cls, v: datetime) -> datetime:
        from datetime import timezone
        now = datetime.now(timezone.utc)
        if v.tzinfo is None:
            raise ValueError("scheduled_start must include timezone info")
        if v <= now:
            raise ValueError("scheduled_start must be in the future")
        return v


class ServiceTypeSummary(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    name: str
    duration_minutes: int


class ServiceBaySummary(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    label: str


class TechnicianSummary(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    name: str


class AppointmentOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    customer_id: str
    vehicle_id: str
    dealership_id: str
    service_type: ServiceTypeSummary
    service_bay: ServiceBaySummary
    technician: TechnicianSummary
    scheduled_start: datetime
    scheduled_end: datetime
    status: str
    created_at: datetime
    cancelled_at: datetime | None = None


class AppointmentCancelOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    status: str
    cancelled_at: datetime | None


class AppointmentListOut(BaseModel):
    data: list[AppointmentOut]
    pagination: "Pagination"


class Pagination(BaseModel):
    page: int
    limit: int
    total: int


# ── Availability ──────────────────────────────────────────────────────────────

class SlotOut(BaseModel):
    start: datetime
    end: datetime


class AvailabilityOut(BaseModel):
    dealership_id: str
    service_type_id: str
    date: str
    slots: list[SlotOut]
