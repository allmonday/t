"""add pinned column

Revision ID: c8f2a91b3d04
Revises: a3f1b7c92e01
Create Date: 2026-05-14 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8f2a91b3d04'
down_revision: Union[str, Sequence[str], None] = 'a3f1b7c92e01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('todos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pinned', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('todos', schema=None) as batch_op:
        batch_op.drop_column('pinned')
