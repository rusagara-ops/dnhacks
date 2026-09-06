"""Two model slots on one physical worker, preserving legacy single-model behavior."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = 'b731c5ae204f'
down_revision = 'a92e8f37d610'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('workers', sa.Column('models', postgresql.JSONB(), nullable=False, server_default='[]'), schema='coordinator')
    op.add_column('tasks', sa.Column('model_slot', sa.Text(), nullable=False, server_default=''), schema='coordinator')
    op.drop_constraint('worker_single_task', 'workers', schema='coordinator', type_='check')
    op.create_check_constraint('worker_single_task', 'workers', 'active_tasks BETWEEN 0 AND 2', schema='coordinator')
    op.drop_index('uq_tasks_active_worker', table_name='tasks', schema='coordinator')
    op.create_index('uq_tasks_active_worker', 'tasks', ['assigned_worker_id', 'model_slot'], unique=True,
                    postgresql_where=sa.text("status IN ('ASSIGNED','RUNNING')"), schema='coordinator')

def downgrade():
    # Refuse unsafe rollback while a machine has concurrent assignments.
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM coordinator.tasks WHERE status IN ('ASSIGNED','RUNNING') GROUP BY assigned_worker_id HAVING count(*) > 1) THEN RAISE EXCEPTION 'Drain concurrent tasks before downgrade'; END IF; END $$")
    op.drop_index('uq_tasks_active_worker', table_name='tasks', schema='coordinator')
    op.create_index('uq_tasks_active_worker', 'tasks', ['assigned_worker_id'], unique=True,
                    postgresql_where=sa.text("status IN ('ASSIGNED','RUNNING')"), schema='coordinator')
    op.drop_column('tasks', 'model_slot', schema='coordinator')
    op.drop_column('workers', 'models', schema='coordinator')
    op.drop_constraint('worker_single_task', 'workers', schema='coordinator', type_='check')
    op.create_check_constraint('worker_single_task', 'workers', 'active_tasks BETWEEN 0 AND 1', schema='coordinator')
