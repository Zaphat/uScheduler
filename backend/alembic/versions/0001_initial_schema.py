"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_customers_email", "customers", ["email"])

    op.create_table(
        "vehicles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("make", sa.String(50), nullable=False),
        sa.Column("model", sa.String(50), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("vin", sa.String(17), nullable=True, unique=True),
        sa.Column("license_plate", sa.String(20), nullable=True),
    )
    op.create_index("ix_vehicles_customer_id", "vehicles", ["customer_id"])

    op.create_table(
        "dealerships",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="UTC"),
        sa.Column("opening_time", sa.String(5), nullable=False, server_default="08:00"),
        sa.Column("closing_time", sa.String(5), nullable=False, server_default="18:00"),
    )

    op.create_table(
        "service_types",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("required_skills", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"),
    )

    op.create_table(
        "service_bays",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("dealership_id", sa.String(), sa.ForeignKey("dealerships.id"), nullable=False),
        sa.Column("label", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_service_bays_dealership_id", "service_bays", ["dealership_id"])

    op.create_table(
        "technicians",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("dealership_id", sa.String(), sa.ForeignKey("dealerships.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("skills", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_technicians_dealership_id", "technicians", ["dealership_id"])

    op.create_table(
        "appointments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("vehicle_id", sa.String(), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("dealership_id", sa.String(), sa.ForeignKey("dealerships.id"), nullable=False),
        sa.Column("service_type_id", sa.String(), sa.ForeignKey("service_types.id"), nullable=False),
        sa.Column("service_bay_id", sa.String(), sa.ForeignKey("service_bays.id"), nullable=False),
        sa.Column("technician_id", sa.String(), sa.ForeignKey("technicians.id"), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="CONFIRMED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_appointments_customer_id", "appointments", ["customer_id"])
    op.create_index("ix_appointments_dealership_id", "appointments", ["dealership_id"])
    op.create_index("ix_appointments_service_bay_id", "appointments", ["service_bay_id"])
    op.create_index("ix_appointments_technician_id", "appointments", ["technician_id"])
    op.create_index("ix_appointments_scheduled_start", "appointments", ["scheduled_start"])
    op.create_index(
        "ix_appointments_bay_status_times",
        "appointments",
        ["service_bay_id", "status", "scheduled_start", "scheduled_end"],
    )
    op.create_index(
        "ix_appointments_tech_status_times",
        "appointments",
        ["technician_id", "status", "scheduled_start", "scheduled_end"],
    )


def downgrade() -> None:
    op.drop_table("appointments")
    op.drop_table("technicians")
    op.drop_table("service_bays")
    op.drop_table("service_types")
    op.drop_table("dealerships")
    op.drop_table("vehicles")
    op.drop_table("customers")
