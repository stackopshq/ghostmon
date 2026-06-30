"""add snmp monitor type

Revision ID: 67ae1a6497a1
Revises: 3a74991325ac
Create Date: 2026-06-30 16:42:51.854267

"""

from collections.abc import Sequence

from alembic import op

revision: str = "67ae1a6497a1"
down_revision: str | Sequence[str] | None = "3a74991325ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE monitor_type ADD VALUE IF NOT EXISTS 'SNMP'")


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an enum type, so this is intentionally
    # irreversible. Removing SNMP would require recreating the type and rewriting
    # the monitors table — out of scope for a downgrade.
    pass
