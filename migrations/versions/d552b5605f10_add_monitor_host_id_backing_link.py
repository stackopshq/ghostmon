"""add monitor host_id backing link

Revision ID: d552b5605f10
Revises: b037c16b9c73
Create Date: 2026-06-30 14:47:24.381094

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d552b5605f10"
down_revision: str | Sequence[str] | None = "b037c16b9c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("monitors", sa.Column("host_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_monitors_host_id",
        "monitors",
        "hosts",
        ["host_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_monitors_host_id", "monitors", type_="foreignkey")
    op.drop_column("monitors", "host_id")
