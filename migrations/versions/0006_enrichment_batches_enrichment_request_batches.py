"""enrichment request batches

Revision ID: 0006_enrichment_batches
Revises: 62e1356fadde
Create Date: 2026-10-02 11:02:31.822926
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '0006_enrichment_batches'
down_revision: Union[str, None] = '62e1356fadde'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from importlib.resources import files
    op.execute("""DO $$ BEGIN
        IF NOT pg_try_advisory_xact_lock(741205, 2) THEN
            RAISE EXCEPTION 'An enrichment worker is running; retry migration after it finishes';
        END IF;
    END $$""")
    op.execute(files('joblake').joinpath('sql/enrichment_batches.sql').read_text(encoding='utf-8'))


def downgrade() -> None:
    raise RuntimeError('Forward-only: preserve request quota and per-job attempt history')
