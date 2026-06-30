"""add triggers and channel min_severity

Revision ID: 6668dc620fe7
Revises: 2262219b743a
Create Date: 2026-06-30 14:10:13.463117

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6668dc620fe7"
down_revision: str | Sequence[str] | None = "2262219b743a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `alert_severity` is shared by triggers.severity and notification_channels.min_severity,
# so the PG enum types are created once up front (create_type=False on the columns).
_trigger_metric = postgresql.ENUM("LATENCY_MS", name="trigger_metric", create_type=False)
_trigger_operator = postgresql.ENUM(
    "GT", "GE", "LT", "LE", name="trigger_operator", create_type=False
)
_trigger_state = postgresql.ENUM("OK", "PROBLEM", name="trigger_state", create_type=False)
_alert_severity = postgresql.ENUM(
    "INFO", "WARNING", "AVERAGE", "HIGH", "DISASTER", name="alert_severity", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (_trigger_metric, _trigger_operator, _trigger_state, _alert_severity):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "triggers",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("monitor_id", sa.UUID(), nullable=False),
        sa.Column("metric", _trigger_metric, nullable=False),
        sa.Column("operator", _trigger_operator, nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("severity", _alert_severity, nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("state", _trigger_state, server_default="OK", nullable=False),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_triggers_monitor_id"), "triggers", ["monitor_id"], unique=False)
    op.add_column(
        "notification_channels",
        sa.Column("min_severity", _alert_severity, server_default="INFO", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("notification_channels", "min_severity")
    op.drop_index(op.f("ix_triggers_monitor_id"), table_name="triggers")
    op.drop_table("triggers")
    op.execute("DROP TYPE IF EXISTS trigger_metric")
    op.execute("DROP TYPE IF EXISTS trigger_operator")
    op.execute("DROP TYPE IF EXISTS trigger_state")
    op.execute("DROP TYPE IF EXISTS alert_severity")
