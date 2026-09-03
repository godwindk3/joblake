"""Create PostgreSQL parsed-job schemas and tables.

Revision ID: 0001_parsed_jobs
Revises:
Create Date: 2026-09-03
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_parsed_jobs"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ref")
    op.execute("CREATE SCHEMA IF NOT EXISTS core")

    op.create_table(
        "sources",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "code",
            name="uq_sources_code",
        ),
        schema="ref",
    )

    op.create_table(
        "source_job_postings",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column(
            "source_external_job_id",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "crawler_job_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["ref.sources.id"],
            name="fk_source_job_postings_source",
        ),
        sa.UniqueConstraint(
            "source_id",
            "canonical_url",
            name="uq_source_job_postings_source_url",
        ),
        schema="core",
    )

    op.create_index(
        "ix_source_job_postings_crawler_job",
        "source_job_postings",
        ["crawler_job_id"],
        schema="core",
    )

    op.create_table(
        "job_parse_results",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column(
            "source_posting_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "crawler_raw_object_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "raw_storage_provider",
            sa.Text(),
            nullable=False,
        ),
        sa.Column("raw_bucket", sa.Text(), nullable=False),
        sa.Column(
            "raw_object_key",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "raw_object_version",
            sa.Text(),
            nullable=True,
        ),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("parser_name", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column(
            "parsed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "quality_status",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "completeness_score",
            sa.SmallInteger(),
            nullable=False,
        ),
        sa.Column(
            "missing_fields",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "employer_name_raw",
            sa.Text(),
            nullable=True,
        ),
        sa.Column("source_variant", sa.Text(), nullable=True),
        sa.Column(
            "description_text",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "requirements_text",
            sa.Text(),
            nullable=True,
        ),
        sa.Column("benefits_text", sa.Text(), nullable=True),
        sa.Column(
            "domains_raw",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "categories_raw",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "skills_raw",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "locations_raw",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "benefit_items",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("salary_raw", sa.Text(), nullable=True),
        sa.Column(
            "employment_type_raw",
            sa.Text(),
            nullable=True,
        ),
        sa.Column("experience_raw", sa.Text(), nullable=True),
        sa.Column(
            "posted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "source_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "quality_status IN ('accepted', 'partial', 'rejected')",
            name="ck_job_parse_results_quality_status",
        ),
        sa.CheckConstraint(
            "completeness_score BETWEEN 0 AND 100",
            name="ck_job_parse_results_completeness_score",
        ),
        sa.ForeignKeyConstraint(
            ["source_posting_id"],
            ["core.source_job_postings.id"],
            name="fk_job_parse_results_source_posting",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "source_posting_id",
            "raw_sha256",
            "parser_name",
            "parser_version",
            name="uq_job_parse_results_identity",
        ),
        schema="core",
    )

    op.create_index(
        "uq_job_parse_results_current",
        "job_parse_results",
        ["source_posting_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("is_current = TRUE"),
    )
    op.create_index(
        "ix_job_parse_results_raw_object",
        "job_parse_results",
        ["crawler_raw_object_id"],
        schema="core",
    )
    op.create_index(
        "ix_job_parse_results_parser",
        "job_parse_results",
        ["parser_name", "parser_version", "parsed_at"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_parse_results_parser",
        table_name="job_parse_results",
        schema="core",
    )
    op.drop_index(
        "ix_job_parse_results_raw_object",
        table_name="job_parse_results",
        schema="core",
    )
    op.drop_index(
        "uq_job_parse_results_current",
        table_name="job_parse_results",
        schema="core",
    )
    op.drop_table("job_parse_results", schema="core")
    op.drop_index(
        "ix_source_job_postings_crawler_job",
        table_name="source_job_postings",
        schema="core",
    )
    op.drop_table("source_job_postings", schema="core")
    op.drop_table("sources", schema="ref")
    op.execute("DROP SCHEMA IF EXISTS core")
    op.execute("DROP SCHEMA IF EXISTS ref")
