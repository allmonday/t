"""add pomodoro_sessions table

Revision ID: a3f1b7c92e01
Revises: d75c6f862ec4
Create Date: 2026-04-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f1b7c92e01'
down_revision: Union[str, Sequence[str], None] = 'd75c6f862ec4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'pomodoro_sessions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('started_at', sa.Text(), nullable=False),
        sa.Column('finished_at', sa.Text(), nullable=False),
        sa.Column('phase', sa.Text(), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('completed', sa.Integer(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_pomodoro_started', 'pomodoro_sessions', ['started_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_pomodoro_started', table_name='pomodoro_sessions')
    op.drop_table('pomodoro_sessions')
