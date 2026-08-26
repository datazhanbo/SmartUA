"""phase4_4 durable background jobs

Revision ID: 6c0b1d9e4a3f
Revises: a3e6a8c67106
Create Date: 2026-08-26 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6c0b1d9e4a3f'
down_revision: Union[str, Sequence[str], None] = 'a3e6a8c67106'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_jobs',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('job_type', sa.String(length=64), nullable=False),
        sa.Column('idempotency_key', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('app_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name='uq_agent_jobs_idempotency'),
    )
    op.create_index('ix_agent_jobs_app_id', 'agent_jobs', ['app_id'], unique=False)
    op.create_index('ix_agent_jobs_job_type', 'agent_jobs', ['job_type'], unique=False)
    op.create_index('ix_agent_jobs_scheduled_at', 'agent_jobs', ['scheduled_at'], unique=False)
    op.create_index('ix_agent_jobs_status', 'agent_jobs', ['status'], unique=False)
    op.create_index('ix_agent_jobs_due', 'agent_jobs', ['status', 'scheduled_at'], unique=False)
    op.create_index('ix_agent_jobs_type_status', 'agent_jobs', ['job_type', 'status'], unique=False)

    # P2 #4：impact 回采统一收敛到 agent_jobs，旧专用表下线。
    op.drop_index('ix_impact_jobs_due', table_name='agent_impact_jobs')
    op.drop_table('agent_impact_jobs')


def downgrade() -> None:
    # 重建旧 agent_impact_jobs（结构对齐 6aff1c23d194）
    op.create_table(
        'agent_impact_jobs',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('action_id', sa.String(length=32), nullable=False),
        sa.Column('app_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('window', sa.String(length=8), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(), nullable=False),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('envelope_json', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['action_id'], ['agent_actions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('action_id', 'kind', 'window',
                            name='uq_impact_job_action_kind_window'),
    )
    op.create_index('ix_impact_jobs_due', 'agent_impact_jobs',
                    ['status', 'scheduled_at'], unique=False)
    op.create_index(op.f('ix_agent_impact_jobs_action_id'), 'agent_impact_jobs',
                    ['action_id'], unique=False)
    op.create_index(op.f('ix_agent_impact_jobs_app_id'), 'agent_impact_jobs',
                    ['app_id'], unique=False)
    op.create_index(op.f('ix_agent_impact_jobs_scheduled_at'), 'agent_impact_jobs',
                    ['scheduled_at'], unique=False)
    op.create_index(op.f('ix_agent_impact_jobs_status'), 'agent_impact_jobs',
                    ['status'], unique=False)

    op.drop_index('ix_agent_jobs_type_status', table_name='agent_jobs')
    op.drop_index('ix_agent_jobs_due', table_name='agent_jobs')
    op.drop_index('ix_agent_jobs_status', table_name='agent_jobs')
    op.drop_index('ix_agent_jobs_scheduled_at', table_name='agent_jobs')
    op.drop_index('ix_agent_jobs_job_type', table_name='agent_jobs')
    op.drop_index('ix_agent_jobs_app_id', table_name='agent_jobs')
    op.drop_table('agent_jobs')
