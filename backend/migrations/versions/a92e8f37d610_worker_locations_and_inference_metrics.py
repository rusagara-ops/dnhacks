"""Optional worker locations, explicit job targeting, and inference measurements."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a92e8f37d610'
down_revision = '78ccab156bc1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('workers', sa.Column('location', postgresql.JSONB(), nullable=True), schema='coordinator')
    op.add_column('jobs', sa.Column('target_worker_id', sa.Uuid(), nullable=True), schema='coordinator')
    op.create_foreign_key('fk_jobs_target_worker', 'jobs', 'workers', ['target_worker_id'], ['id'],
                          source_schema='coordinator', referent_schema='coordinator')
    op.create_index('ix_coordinator_jobs_target_worker_id', 'jobs', ['target_worker_id'], schema='coordinator')
    op.add_column('task_results', sa.Column('inference_metrics', postgresql.JSONB(), nullable=True), schema='coordinator')


def downgrade():
    op.drop_column('task_results', 'inference_metrics', schema='coordinator')
    op.drop_index('ix_coordinator_jobs_target_worker_id', table_name='jobs', schema='coordinator')
    op.drop_constraint('fk_jobs_target_worker', 'jobs', schema='coordinator', type_='foreignkey')
    op.drop_column('jobs', 'target_worker_id', schema='coordinator')
    op.drop_column('workers', 'location', schema='coordinator')
