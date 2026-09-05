"""Pin model per job and enforce one active assignment per worker."""
from alembic import op
import sqlalchemy as sa

revision = '9e9ad9dc65c4'
down_revision = '1781ed678f6b'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('jobs', sa.Column('model_id', sa.Text(), nullable=True), schema='coordinator')
    op.add_column('jobs', sa.Column('model_revision', sa.Text(), nullable=True), schema='coordinator')
    op.create_index('uq_tasks_active_worker', 'tasks', ['assigned_worker_id'], unique=True,
                    schema='coordinator', postgresql_where=sa.text("status IN ('ASSIGNED','RUNNING')"))


def downgrade():
    op.drop_index('uq_tasks_active_worker', table_name='tasks', schema='coordinator')
    op.drop_column('jobs', 'model_revision', schema='coordinator')
    op.drop_column('jobs', 'model_id', schema='coordinator')
