"""Add quarantined upload metadata and chunk embeddings for Phase 3 ingestion.

Revision ID: 20260809_0006
Revises: 20260809_0005
"""

import sqlalchemy as sa

from alembic import op

revision = "20260809_0006"
down_revision = "20260809_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("object_key", sa.String(512)))
    op.add_column("documents", sa.Column("content_type", sa.String(128)))
    op.add_column("documents", sa.Column("size_bytes", sa.BigInteger()))
    op.add_column("documents", sa.Column("original_filename", sa.String(256)))
    op.add_column("documents", sa.Column("failure_reason", sa.Text()))
    op.add_column("document_chunks", sa.Column("embedding", sa.ARRAY(sa.Float())))
    op.add_column("document_chunks", sa.Column("embedding_model", sa.String(120)))


def downgrade() -> None:
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "embedding")
    op.drop_column("documents", "failure_reason")
    op.drop_column("documents", "original_filename")
    op.drop_column("documents", "size_bytes")
    op.drop_column("documents", "content_type")
    op.drop_column("documents", "object_key")
