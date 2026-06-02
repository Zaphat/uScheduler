import json
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, ForeignKey, DateTime, Integer, SmallInteger, Text, TypeDecorator, types as sa_types
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class ArrayOfString(TypeDecorator):
    """Stores list[str] as PostgreSQL ARRAY(String) or JSON text on other dialects.

    This allows the same ORM model to work against both production PostgreSQL
    and the SQLite in-memory database used in unit tests.
    """

    impl = sa_types.Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import ARRAY
            return dialect.type_descriptor(ARRAY(String))
        return dialect.type_descriptor(sa_types.Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name != "postgresql":
            return json.dumps(value)
        return value  # asyncpg handles list → pg array natively

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if dialect.name != "postgresql" and isinstance(value, str):
            return json.loads(value)
        return value


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="CUSTOMER")
    dealership_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("dealerships.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="customer")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="customer")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), index=True)
    make: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(50))
    year: Mapped[int] = mapped_column(SmallInteger)
    vin: Mapped[str | None] = mapped_column(String(17), unique=True)
    license_plate: Mapped[str | None] = mapped_column(String(20))

    customer: Mapped["Customer"] = relationship(back_populates="vehicles")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="vehicle")


class Dealership(Base):
    __tablename__ = "dealerships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    opening_time: Mapped[str] = mapped_column(String(5), default="08:00")   # "HH:MM"
    closing_time: Mapped[str] = mapped_column(String(5), default="18:00")

    bays: Mapped[list["ServiceBay"]] = relationship(back_populates="dealership")
    technicians: Mapped[list["Technician"]] = relationship(back_populates="dealership")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="dealership")


class ServiceType(Base):
    __tablename__ = "service_types"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dealership_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("dealerships.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    required_skills: Mapped[list] = mapped_column(ArrayOfString, default=list)

    appointments: Mapped[list["Appointment"]] = relationship(back_populates="service_type")


class ServiceBay(Base):
    __tablename__ = "service_bays"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dealership_id: Mapped[str] = mapped_column(String(36), ForeignKey("dealerships.id"), index=True)
    label: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    dealership: Mapped["Dealership"] = relationship(back_populates="bays")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="service_bay")


class Technician(Base):
    __tablename__ = "technicians"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dealership_id: Mapped[str] = mapped_column(String(36), ForeignKey("dealerships.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    skills: Mapped[list] = mapped_column(ArrayOfString, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    dealership: Mapped["Dealership"] = relationship(back_populates="technicians")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="technician")


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), index=True)
    vehicle_id: Mapped[str] = mapped_column(String(36), ForeignKey("vehicles.id"))
    dealership_id: Mapped[str] = mapped_column(String(36), ForeignKey("dealerships.id"), index=True)
    service_type_id: Mapped[str] = mapped_column(String(36), ForeignKey("service_types.id"))
    service_bay_id: Mapped[str] = mapped_column(String(36), ForeignKey("service_bays.id"), index=True)
    technician_id: Mapped[str] = mapped_column(String(36), ForeignKey("technicians.id"), index=True)
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="CONFIRMED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    customer: Mapped["Customer"] = relationship(back_populates="appointments")
    vehicle: Mapped["Vehicle"] = relationship(back_populates="appointments")
    dealership: Mapped["Dealership"] = relationship(back_populates="appointments")
    service_type: Mapped["ServiceType"] = relationship(back_populates="appointments")
    service_bay: Mapped["ServiceBay"] = relationship(back_populates="appointments")
    technician: Mapped["Technician"] = relationship(back_populates="appointments")
