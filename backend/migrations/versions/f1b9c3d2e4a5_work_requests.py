"""Add provider-mediated work requests."""

from alembic import op
import sqlalchemy as sa


revision = 'f1b9c3d2e4a5'
down_revision = 'c84d12e6a901'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'work_requests',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('requester_account_id', sa.Uuid(), nullable=False),
        sa.Column('provider_account_id', sa.Uuid(), nullable=False),
        sa.Column('worker_id', sa.Uuid(), nullable=False),
        sa.Column('task_type', sa.Text(), nullable=False),
        sa.Column('model_id', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), server_default='PENDING', nullable=False),
        sa.Column('job_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('PENDING','APPROVED','DECLINED','USED','EXPIRED')", name='work_request_status_valid'),
        sa.CheckConstraint('requester_account_id <> provider_account_id', name='work_request_distinct_accounts'),
        sa.ForeignKeyConstraint(['requester_account_id'], ['coordinator.accounts.id']),
        sa.ForeignKeyConstraint(['provider_account_id'], ['coordinator.accounts.id']),
        sa.ForeignKeyConstraint(['worker_id'], ['coordinator.workers.id']),
        sa.ForeignKeyConstraint(['job_id'], ['coordinator.jobs.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_id'),
        schema='coordinator',
    )
    op.create_index('ix_work_requests_requester_account_id', 'work_requests', ['requester_account_id'], schema='coordinator')
    op.create_index('ix_work_requests_provider_account_id', 'work_requests', ['provider_account_id'], schema='coordinator')
    op.create_index('ix_work_requests_worker_id', 'work_requests', ['worker_id'], schema='coordinator')
    op.create_index('ix_work_requests_status', 'work_requests', ['status'], schema='coordinator')


def downgrade():
    op.drop_index('ix_work_requests_status', table_name='work_requests', schema='coordinator')
    op.drop_index('ix_work_requests_worker_id', table_name='work_requests', schema='coordinator')
    op.drop_index('ix_work_requests_provider_account_id', table_name='work_requests', schema='coordinator')
    op.drop_index('ix_work_requests_requester_account_id', table_name='work_requests', schema='coordinator')
    op.drop_table('work_requests', schema='coordinator')
