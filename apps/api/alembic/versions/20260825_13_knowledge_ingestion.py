"""Add provider-neutral knowledge ingestion and retrieval.

Revision ID: 20260825_13
Revises: 20260825_12
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "20260825_13"
down_revision: str | None = "20260825_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_uri", sa.String(length=2048), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by_owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "source_type IN ('upload', 'reference')",
            name="ck_knowledge_sources_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'invalidated')",
            name="ck_knowledge_sources_status",
        ),
        sa.CheckConstraint("revision > 0", name="ck_knowledge_sources_revision"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "business_id", name="uq_knowledge_sources_scope"),
    )
    op.create_index(
        "ix_knowledge_sources_business_status",
        "knowledge_sources",
        ["business_id", "status", "created_at"],
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("storage_key", sa.String(length=600), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("extraction_version", sa.String(length=80), nullable=False),
        sa.Column("embedding_model", sa.String(length=120), nullable=False),
        sa.Column("embedding_dimensions", sa.SmallInteger(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.String(length=500), nullable=True),
        sa.CheckConstraint("byte_size > 0", name="ck_knowledge_documents_byte_size"),
        sa.CheckConstraint(
            "embedding_dimensions > 0",
            name="ck_knowledge_documents_embedding_dimensions",
        ),
        sa.CheckConstraint(
            "character_count > 0 AND chunk_count > 0",
            name="ck_knowledge_documents_content_counts",
        ),
        sa.CheckConstraint(
            "status IN ('indexed', 'invalidated')",
            name="ck_knowledge_documents_status",
        ),
        sa.CheckConstraint("revision > 0", name="ck_knowledge_documents_revision"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_id", "business_id"],
            ["knowledge_sources.id", "knowledge_sources.business_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "business_id", "source_id", name="uq_knowledge_documents_scope"),
        sa.UniqueConstraint(
            "source_id", "content_sha256", name="uq_knowledge_documents_source_content"
        ),
        sa.UniqueConstraint("storage_key", name="uq_knowledge_documents_storage_key"),
    )
    op.create_index(
        "ix_knowledge_documents_business_status",
        "knowledge_documents",
        ["business_id", "status", "created_at"],
    )
    op.create_index("ix_knowledge_documents_source_id", "knowledge_documents", ["source_id"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_character", sa.Integer(), nullable=False),
        sa.Column("end_character", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("estimated_tokens", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(length=120), nullable=False),
        sa.Column("embedding", Vector(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_document_chunks_ordinal"),
        sa.CheckConstraint(
            "start_character >= 0 AND end_character > start_character",
            name="ck_document_chunks_offsets",
        ),
        sa.CheckConstraint("estimated_tokens > 0", name="ck_document_chunks_tokens"),
        sa.ForeignKeyConstraint(
            ["document_id", "business_id", "source_id"],
            [
                "knowledge_documents.id",
                "knowledge_documents.business_id",
                "knowledge_documents.source_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_document_chunks_ordinal"),
    )
    op.create_index(
        "ix_document_chunks_business_document",
        "document_chunks",
        ["business_id", "document_id", "ordinal"],
    )
    op.create_index("ix_document_chunks_source_id", "document_chunks", ["source_id"])
    op.create_index(
        "ix_document_chunks_embedding_cosine",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_embedding_cosine", table_name="document_chunks")
    op.drop_index("ix_document_chunks_source_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_business_document", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_knowledge_documents_source_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_business_status", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index("ix_knowledge_sources_business_status", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
    op.execute("DROP EXTENSION IF EXISTS vector")
