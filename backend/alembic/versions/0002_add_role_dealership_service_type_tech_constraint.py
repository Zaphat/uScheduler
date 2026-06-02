"""Add role+dealership_id to customers, dealership_id to service_types, technician exclusion constraint

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── customers: role and dealership_id for STAFF/ADMIN token claims ──
    op.add_column(
        "customers",
        sa.Column("role", sa.String(20), nullable=False, server_default="CUSTOMER"),
    )
    op.add_column(
        "customers",
        sa.Column(
            "dealership_id",
            sa.String(),
            sa.ForeignKey("dealerships.id"),
            nullable=True,
        ),
    )

    # ── service_types: scope to dealership ──────────────────────────────
    op.add_column(
        "service_types",
        sa.Column(
            "dealership_id",
            sa.String(),
            sa.ForeignKey("dealerships.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_service_types_dealership_id", "service_types", ["dealership_id"])

    # ── appointments: technician exclusion constraint (Layer 3 – tech) ──
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        ALTER TABLE appointments
          ADD CONSTRAINT no_double_tech_booking
          EXCLUDE USING gist (
            technician_id WITH =,
            tstzrange(scheduled_start, scheduled_end, '[)') WITH &&
          )
          WHERE (status = 'CONFIRMED')
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS no_double_tech_booking")
    op.drop_index("ix_service_types_dealership_id", table_name="service_types")
    op.drop_column("service_types", "dealership_id")
    op.drop_column("customers", "dealership_id")
    op.drop_column("customers", "role")
