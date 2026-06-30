"""add host address and item source config

Revision ID: 3b0c2fc4cfbf
Revises: 67ae1a6497a1
Create Date: 2026-06-30 16:54:42.965822

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3b0c2fc4cfbf"
down_revision: str | Sequence[str] | None = "67ae1a6497a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# op.add_column does not auto-create the enum type under asyncpg; create it first.
_item_source = postgresql.ENUM("TRAPPER", "SNMP", name="item_source", create_type=False)


def upgrade() -> None:
    _item_source.create(op.get_bind(), checkfirst=True)
    op.add_column("hosts", sa.Column("address", sa.String(length=255), nullable=True))
    op.add_column(
        "items",
        sa.Column("source", _item_source, server_default="TRAPPER", nullable=False),
    )
    op.add_column(
        "items",
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("items", "config")
    op.drop_column("items", "source")
    op.drop_column("hosts", "address")
    op.execute("DROP TYPE IF EXISTS item_source")
