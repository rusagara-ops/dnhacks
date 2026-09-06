"""Individual identities, provider admission policies, and demo-credit accounting."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = 'c84d12e6a901'
down_revision = 'b731c5ae204f'
branch_labels = None
depends_on = None
SCHEMA = 'coordinator'


def upgrade():
    op.create_table('accounts',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('role', sa.Text(), nullable=False, server_default='member'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('member','admin')", name='account_role_valid'), schema=SCHEMA)
    op.create_table('credentials',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', pg.UUID(as_uuid=True), sa.ForeignKey('coordinator.accounts.id'), nullable=False),
        sa.Column('token_hash', sa.Text(), nullable=False, unique=True),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('device_id', pg.UUID(as_uuid=True)),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('revoked_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('account','worker')", name='credential_kind_valid'),
        sa.CheckConstraint("(kind = 'worker' AND device_id IS NOT NULL) OR (kind = 'account' AND device_id IS NULL)", name='credential_device_scope_valid'), schema=SCHEMA)
    op.create_index('ix_coordinator_credentials_account_id', 'credentials', ['account_id'], schema=SCHEMA)
    op.create_index('ix_coordinator_credentials_device_id', 'credentials', ['device_id'], schema=SCHEMA)
    for table in ('jobs', 'workers'):
        op.add_column(table, sa.Column('owner_account_id', pg.UUID(as_uuid=True)), schema=SCHEMA)
        op.create_foreign_key(f'{table}_owner_account_fkey', table, 'accounts', ['owner_account_id'], ['id'], source_schema=SCHEMA, referent_schema=SCHEMA)
        op.create_index(f'ix_coordinator_{table}_owner_account_id', table, ['owner_account_id'], schema=SCHEMA)
    op.create_table('wallets',
        sa.Column('account_id', pg.UUID(as_uuid=True), sa.ForeignKey('coordinator.accounts.id'), primary_key=True),
        sa.Column('available', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('reserved', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('lifetime_earned', sa.BigInteger(), nullable=False, server_default='0'),
        sa.CheckConstraint('available >= 0 AND reserved >= 0 AND lifetime_earned >= 0', name='wallet_balances_nonnegative'), schema=SCHEMA)
    op.create_table('credit_entries',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', pg.UUID(as_uuid=True), sa.ForeignKey('coordinator.accounts.id'), nullable=False),
        sa.Column('job_id', pg.UUID(as_uuid=True), sa.ForeignKey('coordinator.jobs.id')),
        sa.Column('task_id', pg.UUID(as_uuid=True), sa.ForeignKey('coordinator.tasks.id')),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('available_delta', sa.BigInteger(), nullable=False),
        sa.Column('reserved_delta', sa.BigInteger(), nullable=False),
        sa.Column('earned_delta', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('idempotency_key', sa.Text(), nullable=False, unique=True),
        sa.Column('pricing_version', sa.Text(), nullable=False, server_default='demo-v1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('grant','reserve','spend','earn','refund')", name='credit_entry_kind_valid'),
        sa.CheckConstraint("(kind = 'grant' AND available_delta > 0 AND reserved_delta = 0 AND earned_delta = 0) OR "
            "(kind = 'reserve' AND available_delta < 0 AND reserved_delta = -available_delta AND earned_delta = 0) OR "
            "(kind = 'spend' AND available_delta = 0 AND reserved_delta < 0 AND earned_delta = 0) OR "
            "(kind = 'earn' AND available_delta > 0 AND reserved_delta = 0 AND earned_delta = available_delta) OR "
            "(kind = 'refund' AND available_delta > 0 AND reserved_delta = -available_delta AND earned_delta = 0)", name='credit_entry_deltas_valid'),
        sa.CheckConstraint("(kind = 'grant' AND job_id IS NULL AND task_id IS NULL) OR "
            "(kind = 'reserve' AND job_id IS NOT NULL AND task_id IS NULL) OR "
            "(kind IN ('spend','earn','refund') AND job_id IS NOT NULL AND task_id IS NOT NULL)", name='credit_entry_references_valid'), schema=SCHEMA)
    for column in ('account_id', 'job_id', 'task_id', 'created_at'):
        op.create_index(f'ix_coordinator_credit_entries_{column}', 'credit_entries', [column], schema=SCHEMA)
    op.execute("""CREATE FUNCTION coordinator.reject_credit_entry_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Credit ledger is append-only'; END; $$""")
    op.execute('CREATE TRIGGER credit_entries_immutable BEFORE UPDATE OR DELETE ON coordinator.credit_entries FOR EACH ROW EXECUTE FUNCTION coordinator.reject_credit_entry_mutation()')
    op.execute('CREATE TRIGGER credit_entries_no_truncate BEFORE TRUNCATE ON coordinator.credit_entries FOR EACH STATEMENT EXECUTE FUNCTION coordinator.reject_credit_entry_mutation()')
    op.create_table('provider_policies',
        sa.Column('worker_id', pg.UUID(as_uuid=True), sa.ForeignKey('coordinator.workers.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('sharing_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('allowed_task_types', pg.JSONB(), nullable=False),
        sa.Column('max_concurrent_tasks', sa.Integer(), nullable=False),
        sa.Column('min_ram_available_gb', sa.Float(), nullable=False),
        sa.Column('availability', pg.JSONB(), nullable=False, server_default='[]'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('max_concurrent_tasks BETWEEN 1 AND 2', name='provider_concurrency_range'),
        sa.CheckConstraint('min_ram_available_gb >= 0', name='provider_ram_nonnegative'), schema=SCHEMA)
    op.create_table('execution_attempts',
        sa.Column('assignment_id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('task_id', pg.UUID(as_uuid=True), sa.ForeignKey('coordinator.tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('worker_id', pg.UUID(as_uuid=True), sa.ForeignKey('coordinator.workers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True)),
        sa.Column('reported_execution_ms', sa.Integer()),
        sa.CheckConstraint("status IN ('ASSIGNED','COMPLETED','FAILED','EXPIRED')", name='attempt_status_valid'),
        sa.CheckConstraint('reported_execution_ms IS NULL OR reported_execution_ms >= 0', name='attempt_runtime_nonnegative'), schema=SCHEMA)
    for column in ('task_id', 'worker_id'):
        op.create_index(f'ix_coordinator_execution_attempts_{column}', 'execution_attempts', [column], schema=SCHEMA)
    # Match the coordinator's existing private-schema posture. The backend's
    # database owner/service role mediates access; browser users get no SQL role.
    for table in ('accounts', 'credentials', 'wallets', 'credit_entries', 'provider_policies', 'execution_attempts'):
        op.execute(f'ALTER TABLE coordinator.{table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON coordinator.{table} FROM PUBLIC')
    op.execute('REVOKE ALL ON FUNCTION coordinator.reject_credit_entry_mutation() FROM PUBLIC')


def downgrade():
    # Reverting application code can retain this additive schema. Never silently
    # destroy account or accounting history as part of a demo rollback.
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM coordinator.accounts) THEN RAISE EXCEPTION 'Preserve sharing accounts and ledger; revert application code without dropping this schema'; END IF; END $$")
    for table in ('execution_attempts', 'provider_policies', 'credit_entries', 'wallets'):
        op.drop_table(table, schema=SCHEMA)
    op.execute('DROP FUNCTION coordinator.reject_credit_entry_mutation()')
    for table in ('jobs', 'workers'):
        op.drop_column(table, 'owner_account_id', schema=SCHEMA)
    op.drop_table('credentials', schema=SCHEMA)
    op.drop_table('accounts', schema=SCHEMA)
