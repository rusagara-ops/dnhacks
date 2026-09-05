"""Create coordinator worker registry."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '619fef38fe94'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE SCHEMA IF NOT EXISTS coordinator')
    op.execute('REVOKE ALL ON SCHEMA coordinator FROM PUBLIC')
    op.create_table(
        'workers',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('hostname', sa.Text(), nullable=False),
        sa.Column('cpu', sa.Text(), nullable=False),
        sa.Column('cpu_cores', sa.Integer(), nullable=False),
        sa.Column('ram_gb', sa.Float(), nullable=False),
        sa.Column('gpu', sa.Text()),
        sa.Column('gpu_memory_gb', sa.Float()),
        sa.Column('supported_tasks', postgresql.JSONB(), nullable=False),
        sa.Column('model_id', sa.Text()),
        sa.Column('model_revision', sa.Text()),
        sa.Column('benchmark_score', sa.Float(), nullable=False),
        sa.Column('cpu_utilization', sa.Float(), nullable=False),
        sa.Column('memory_utilization', sa.Float(), nullable=False),
        sa.Column('active_tasks', sa.Integer(), nullable=False),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('cpu_cores > 0', name='worker_cpu_positive'),
        sa.CheckConstraint('ram_gb > 0', name='worker_ram_positive'),
        sa.CheckConstraint('gpu_memory_gb IS NULL OR gpu_memory_gb >= 0', name='worker_gpu_memory_nonnegative'),
        sa.CheckConstraint('benchmark_score > 0', name='worker_benchmark_positive'),
        sa.CheckConstraint('cpu_utilization BETWEEN 0 AND 100', name='worker_cpu_utilization_range'),
        sa.CheckConstraint('memory_utilization BETWEEN 0 AND 100', name='worker_memory_utilization_range'),
        sa.CheckConstraint('active_tasks BETWEEN 0 AND 1', name='worker_single_task'),
        schema='coordinator',
    )
    op.create_index('ix_coordinator_workers_last_heartbeat', 'workers', ['last_heartbeat'], schema='coordinator')
    op.execute('ALTER TABLE coordinator.workers ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON coordinator.workers FROM PUBLIC')


def downgrade():
    op.drop_table('workers', schema='coordinator')
    # Leave the schema in place: other migrations/applications may use it.
