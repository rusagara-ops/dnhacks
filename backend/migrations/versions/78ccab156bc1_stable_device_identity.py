"""Persist worker identity across reconnects without deleting historical workers."""
from alembic import op
import sqlalchemy as sa
revision='78ccab156bc1'
down_revision='47bc91eea204'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('workers',sa.Column('device_id',sa.Uuid(),nullable=True),schema='coordinator')
    op.create_unique_constraint('uq_workers_device_id','workers',['device_id'],schema='coordinator')

def downgrade():
    op.drop_constraint('uq_workers_device_id','workers',schema='coordinator',type_='unique')
    op.drop_column('workers','device_id',schema='coordinator')
