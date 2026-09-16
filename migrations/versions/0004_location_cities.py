"""Add normalized city labels for website filtering."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_location_cities"
down_revision = "0003_url_cdc"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("job_parse_results", sa.Column(
        "location_cities", postgresql.ARRAY(sa.Text()), nullable=False,
        server_default=sa.text("'{}'::text[]"),
    ), schema="core")
    op.create_index("ix_job_parse_results_location_cities", "job_parse_results",
                    ["location_cities"], schema="core", postgresql_using="gin")


def downgrade():
    op.drop_index("ix_job_parse_results_location_cities", table_name="job_parse_results", schema="core")
    op.drop_column("job_parse_results", "location_cities", schema="core")
