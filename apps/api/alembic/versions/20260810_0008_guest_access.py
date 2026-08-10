"""Add identity kind for guest (trial) access.

Revision ID: 20260810_0008
Revises: 20260809_0007
Create Date: 2026-08-10
"""

import sqlalchemy as sa

from alembic import op

revision = "20260810_0008"
down_revision = "20260809_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("kind", sa.String(16), nullable=False, server_default="person"),
    )


def downgrade() -> None:
    op.drop_column("users", "kind")
