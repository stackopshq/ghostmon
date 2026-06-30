"""add templates and template items

Revision ID: 3a74991325ac
Revises: 97776cea4d1f
Create Date: 2026-06-30 15:49:50.751303

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3a74991325ac"
down_revision: str | Sequence[str] | None = "97776cea4d1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Shared with the `items` table — already created by an earlier migration, so it
# is referenced here without re-creating it.
_item_value_type = postgresql.ENUM(
    "FLOAT", "UNSIGNED", "TEXT", name="item_value_type", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name", name="uq_templates_owner_name"),
    )
    op.create_index(op.f("ix_templates_owner_id"), "templates", ["owner_id"], unique=False)
    op.create_table(
        "template_items",
        sa.Column("template_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("value_type", _item_value_type, nullable=False),
        sa.Column("units", sa.String(length=32), nullable=True),
        sa.Column("interval", sa.Integer(), server_default="60", nullable=False),
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
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "key", name="uq_template_items_template_key"),
    )
    op.create_index(
        op.f("ix_template_items_template_id"), "template_items", ["template_id"], unique=False
    )


def downgrade() -> None:
    # item_value_type is left intact — it is still used by the `items` table.
    op.drop_index(op.f("ix_template_items_template_id"), table_name="template_items")
    op.drop_table("template_items")
    op.drop_index(op.f("ix_templates_owner_id"), table_name="templates")
    op.drop_table("templates")
