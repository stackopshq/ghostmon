"""add trigger aggregation and window

Revision ID: b1976e4b555e
Revises: d552b5605f10
Create Date: 2026-06-30 15:16:54.724124

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1976e4b555e"
down_revision: str | Sequence[str] | None = "d552b5605f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# op.add_column (unlike create_table) does not auto-create the PG enum type, so
# it is created explicitly up front and referenced with create_type=False.
_aggregation = postgresql.ENUM(
    "LAST", "AVG", "MIN", "MAX", name="trigger_aggregation", create_type=False
)


def upgrade() -> None:
    _aggregation.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "triggers",
        sa.Column("aggregation", _aggregation, server_default="LAST", nullable=False),
    )
    op.add_column(
        "triggers", sa.Column("window_seconds", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("triggers", "window_seconds")
    op.drop_column("triggers", "aggregation")
    op.execute("DROP TYPE IF EXISTS trigger_aggregation")
