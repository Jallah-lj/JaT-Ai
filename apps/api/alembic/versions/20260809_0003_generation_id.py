"""Add generation identifier to assistant messages.

Revision ID: 20260809_0003
Revises: 20260809_0002
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260809_0003"
down_revision = "20260809_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("generation_id", postgresql.UUID(as_uuid=True)))
    op.create_unique_constraint("uq_messages_generation_id", "messages", ["generation_id"])


def downgrade() -> None:
    op.drop_constraint("uq_messages_generation_id", "messages", type_="unique")
    op.drop_column("messages", "generation_id")
