"""triggers on items

Revision ID: 7d2d53401fc9
Revises: d83103a6d110
Create Date: 2026-06-30 18:12:56.022041

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7d2d53401fc9"
down_revision: str | Sequence[str] | None = "d83103a6d110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_METRIC = postgresql.ENUM("LATENCY_MS", name="trigger_metric", create_type=False)


def upgrade() -> None:
    op.add_column("triggers", sa.Column("item_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_triggers_item_id", "triggers", "items", ["item_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_triggers_item_id"), "triggers", ["item_id"], unique=False)
    op.alter_column("triggers", "monitor_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column("triggers", "metric", existing_type=_METRIC, nullable=True)
    # A trigger is attached to exactly one of a monitor or an item.
    op.create_check_constraint(
        "ck_triggers_monitor_xor_item", "triggers", "(monitor_id IS NULL) <> (item_id IS NULL)"
    )


def downgrade() -> None:
    op.drop_constraint("ck_triggers_monitor_xor_item", "triggers", type_="check")
    # Item triggers cannot coexist with a NOT NULL monitor_id, so remove them.
    op.execute("DELETE FROM triggers WHERE item_id IS NOT NULL")
    op.alter_column("triggers", "metric", existing_type=_METRIC, nullable=False)
    op.alter_column("triggers", "monitor_id", existing_type=sa.UUID(), nullable=False)
    op.drop_index(op.f("ix_triggers_item_id"), table_name="triggers")
    op.drop_constraint("fk_triggers_item_id", "triggers", type_="foreignkey")
    op.drop_column("triggers", "item_id")
