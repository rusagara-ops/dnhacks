"""Add jobs and queued tasks. Immutable SQL snapshot of the initial schema."""
from alembic import op

revision = '1781ed678f6b'
down_revision = '619fef38fe94'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("\nCREATE TABLE coordinator.jobs (\n\tid UUID NOT NULL, \n\ttask_type TEXT NOT NULL, \n\toptimization TEXT NOT NULL, \n\tstatus TEXT DEFAULT 'QUEUED' NOT NULL, \n\ttotal_inputs INTEGER NOT NULL, \n\ttotal_tasks INTEGER NOT NULL, \n\tcompleted_tasks INTEGER DEFAULT '0' NOT NULL, \n\tfailed_tasks INTEGER DEFAULT '0' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT job_status_valid CHECK (status IN ('QUEUED','RUNNING','COMPLETED','FAILED')), \n\tCONSTRAINT job_totals_positive CHECK (total_inputs > 0 AND total_tasks > 0), \n\tCONSTRAINT job_counts_valid CHECK (completed_tasks >= 0 AND failed_tasks >= 0 AND completed_tasks + failed_tasks <= total_tasks)\n)\n\n")
    op.execute('CREATE INDEX ix_coordinator_jobs_created_at ON coordinator.jobs (created_at)')
    op.execute('ALTER TABLE coordinator.jobs ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON coordinator.jobs FROM PUBLIC')
    op.execute("\nCREATE TABLE coordinator.tasks (\n\tid UUID NOT NULL, \n\tjob_id UUID NOT NULL, \n\tstart_index INTEGER NOT NULL, \n\tinput_count INTEGER NOT NULL, \n\tpayload JSONB NOT NULL, \n\tstatus TEXT DEFAULT 'QUEUED' NOT NULL, \n\tassigned_worker_id UUID, \n\tassignment_id UUID, \n\tlease_expires_at TIMESTAMP WITH TIME ZONE, \n\tattempt_count INTEGER DEFAULT '0' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT task_status_valid CHECK (status IN ('QUEUED','ASSIGNED','RUNNING','COMPLETED','FAILED')), \n\tCONSTRAINT task_chunk_valid CHECK (start_index >= 0 AND input_count BETWEEN 1 AND 25), \n\tCONSTRAINT task_attempts_valid CHECK (attempt_count BETWEEN 0 AND 3), \n\tCONSTRAINT task_job_start_unique UNIQUE (job_id, start_index), \n\tFOREIGN KEY(job_id) REFERENCES coordinator.jobs (id) ON DELETE CASCADE, \n\tFOREIGN KEY(assigned_worker_id) REFERENCES coordinator.workers (id)\n)\n\n")
    op.execute('CREATE INDEX ix_coordinator_tasks_assigned_worker_id ON coordinator.tasks (assigned_worker_id)')
    op.execute('CREATE INDEX ix_coordinator_tasks_job_id ON coordinator.tasks (job_id)')
    op.execute('CREATE INDEX ix_coordinator_tasks_status ON coordinator.tasks (status)')
    op.execute('ALTER TABLE coordinator.tasks ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON coordinator.tasks FROM PUBLIC')

def downgrade():
    op.drop_table("tasks", schema="coordinator")
    op.drop_table("jobs", schema="coordinator")
