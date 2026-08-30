"""make attrition_prediction risk_level nullable

Revision ID: 77d9064ae0ac
Revises: 35b61a4acce8
Create Date: 2026-08-30 00:00:00.000000

Phase 11: PRD F9.7's Low/Medium/High risk-band boundaries are not yet
approved against calibrated-probability evidence (Memory.md decision 70 -
the calibrated High band is thin and likely an undercount). Serving code
must not silently finalize a band value, so risk_level has to be able to
stay unset per prediction until that owner decision lands - the column was
created NOT NULL in the initial schema, before this tension was known.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77d9064ae0ac'
down_revision: Union[str, None] = '35b61a4acce8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('attrition_predictions', schema=None) as batch_op:
        batch_op.alter_column(
            'risk_level',
            existing_type=sa.Enum('low', 'medium', 'high', name='risklevel', native_enum=False, length=32),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('attrition_predictions', schema=None) as batch_op:
        batch_op.alter_column(
            'risk_level',
            existing_type=sa.Enum('low', 'medium', 'high', name='risklevel', native_enum=False, length=32),
            nullable=False,
        )
