"""External integration connections table."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260809_0006"
down_revision = "20260809_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "integration_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("display_label", sa.String(length=160)),
        sa.Column("secret_hash", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="connected"),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "provider", name="uq_integration_org_provider"),
    )
    op.create_index(
        "ix_integration_connections_org",
        "integration_connections",
        ["organization_id"],
    )


def downgrade():
    op.drop_index("ix_integration_connections_org", table_name="integration_connections")
    op.drop_table("integration_connections")
