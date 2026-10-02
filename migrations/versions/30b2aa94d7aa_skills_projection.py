"""skills_projection

Revision ID: 30b2aa94d7aa
Revises: 0006_enrichment_batches
Create Date: 2026-10-02 20:09:05.792129
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '30b2aa94d7aa'
down_revision: Union[str, None] = '0006_enrichment_batches'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from importlib.resources import files
    op.execute(files('joblake').joinpath('sql/skills_local.sql').read_text(encoding='utf-8'))


def downgrade() -> None:
    op.execute('DROP VIEW IF EXISTS core.current_job_skills')
    op.execute('DROP FUNCTION IF EXISTS core.preferred_skills(text[],text[])')
    op.execute('DROP FUNCTION IF EXISTS core.normalize_skills(text[])')
    op.execute('DROP FUNCTION IF EXISTS core.skill_key(text)')
