"""Add CHECK constraint on appointments.status

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-02
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE appointments
          ADD CONSTRAINT ck_appointments_status
          CHECK (status IN ('CONFIRMED', 'CANCELLED', 'COMPLETED'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS ck_appointments_status")
