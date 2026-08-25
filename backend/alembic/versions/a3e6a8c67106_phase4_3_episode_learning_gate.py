"""phase4_3 episode learning gate

Revision ID: a3e6a8c67106
Revises: 6aff1c23d194
Create Date: 2026-07-22 06:13:46.352254

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3e6a8c67106'
down_revision: Union[str, Sequence[str], None] = '6aff1c23d194'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('agent_episodes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('execution_mode', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('data_quality_json', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column(
            'usable_for_learning', sa.Boolean(), nullable=True,
            server_default=sa.text('0')))
        batch_op.add_column(sa.Column('evidence_action_ids_json', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('action_id', sa.String(length=32), nullable=True))
        batch_op.create_index(batch_op.f('ix_agent_episodes_action_id'), ['action_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_episodes_execution_mode'), ['execution_mode'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_episodes_usable_for_learning'), ['usable_for_learning'], unique=False)
        batch_op.create_foreign_key(
            'fk_agent_episodes_action_id', 'agent_actions', ['action_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('agent_episodes', schema=None) as batch_op:
        batch_op.drop_constraint('fk_agent_episodes_action_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_agent_episodes_usable_for_learning'))
        batch_op.drop_index(batch_op.f('ix_agent_episodes_execution_mode'))
        batch_op.drop_index(batch_op.f('ix_agent_episodes_action_id'))
        batch_op.drop_column('action_id')
        batch_op.drop_column('evidence_action_ids_json')
        batch_op.drop_column('usable_for_learning')
        batch_op.drop_column('data_quality_json')
        batch_op.drop_column('execution_mode')
