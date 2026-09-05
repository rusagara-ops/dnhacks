"""Add one result per task and retain failure details for retry deduplication."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '7e2242ffb4de'
down_revision = '9e9ad9dc65c4'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE coordinator.tasks SET started_at = created_at WHERE status IN ('ASSIGNED','RUNNING') AND started_at IS NULL")
    op.add_column('tasks', sa.Column('last_error', postgresql.JSONB(), nullable=True), schema='coordinator')
    op.create_table('task_results',
        sa.Column('task_id', sa.Uuid(), sa.ForeignKey('coordinator.tasks.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('worker_id', sa.Uuid(), sa.ForeignKey('coordinator.workers.id'), nullable=False),
        sa.Column('result', postgresql.JSONB(), nullable=False),
        sa.Column('execution_time_ms', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('execution_time_ms >= 0', name='result_duration_nonnegative'), schema='coordinator')
    op.create_index('ix_coordinator_task_results_worker_id', 'task_results', ['worker_id'], schema='coordinator')
    op.execute('ALTER TABLE coordinator.task_results ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON coordinator.task_results FROM PUBLIC')


def downgrade():
    op.drop_table('task_results', schema='coordinator')
    op.drop_column('tasks', 'last_error', schema='coordinator')
