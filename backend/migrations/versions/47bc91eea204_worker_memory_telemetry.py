"""Nullable resource telemetry keeps existing workers compatible."""
from alembic import op
import sqlalchemy as sa
revision = '47bc91eea204'
down_revision = '7e2242ffb4de'
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in [('gpu_core_count',sa.Integer()), ('gpu_memory_kind',sa.Text()),
                       ('ram_available_gb',sa.Float()), ('gpu_available_gb',sa.Float()),
                       ('gpu_model_memory_gb',sa.Float())]:
        op.add_column('workers',sa.Column(name,kind,nullable=True),schema='coordinator')
    for name, condition in [
        ('worker_gpu_cores_positive','gpu_core_count IS NULL OR gpu_core_count > 0'),
        ('worker_memory_kind_valid',"gpu_memory_kind IS NULL OR gpu_memory_kind IN ('unified','dedicated','unknown')"),
        ('worker_available_ram_range','ram_available_gb IS NULL OR (ram_available_gb >= 0 AND ram_available_gb <= ram_gb)'),
        ('worker_available_gpu_nonnegative','gpu_available_gb IS NULL OR gpu_available_gb >= 0'),
        ('worker_gpu_model_nonnegative','gpu_model_memory_gb IS NULL OR gpu_model_memory_gb >= 0')]:
        op.create_check_constraint(name,'workers',condition,schema='coordinator')


def downgrade():
    for name in ['worker_gpu_cores_positive','worker_memory_kind_valid','worker_available_ram_range',
                 'worker_available_gpu_nonnegative','worker_gpu_model_nonnegative']:
        op.drop_constraint(name,'workers',schema='coordinator',type_='check')
    for name in ['gpu_model_memory_gb','gpu_available_gb','ram_available_gb','gpu_memory_kind','gpu_core_count']:
        op.drop_column('workers',name,schema='coordinator')
