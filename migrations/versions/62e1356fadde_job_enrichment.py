"""job_enrichment

Revision ID: 62e1356fadde
Revises: 0005_raw_cleanup
Create Date: 2026-09-25 18:21:02.021544
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '62e1356fadde'
down_revision: Union[str, None] = '0005_raw_cleanup'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from importlib.resources import files
    op.execute(files('joblake').joinpath('sql/enrichment.sql').read_text(encoding='utf-8'))


def downgrade() -> None:
    raise RuntimeError('Enrichment migration is forward-only; preserve extraction and quota history')
