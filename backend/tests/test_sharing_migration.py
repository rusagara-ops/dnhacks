"""Opt-in migration rehearsal; creates and drops only a generated local test DB."""
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy.engine import make_url


def test_upgrade_preserves_legacy_rows_and_enforces_immutable_private_ledger():
    if os.environ.get('RUN_MIGRATION_TESTS') != '1':
        pytest.skip('Set RUN_MIGRATION_TESTS=1 with a disposable local TEST_DATABASE_URL')
    url = make_url(os.environ['TEST_DATABASE_URL'])
    if url.host not in ('127.0.0.1', 'localhost'):
        pytest.fail('Migration rehearsal requires a disposable local PostgreSQL cluster')
    name = 'dnhacks_migration_' + uuid4().hex
    admin_url = url.set(drivername='postgresql', database='postgres').render_as_string(hide_password=False)
    test_url = url.set(database=name)
    env = dict(os.environ, DATABASE_URL=test_url.render_as_string(hide_password=False), AUTH_MODE='demo')
    cwd = Path(__file__).resolve().parents[1]
    def migrate(*args):
        return subprocess.run([sys.executable, '-m', 'alembic', *args], cwd=cwd, env=env,
                              capture_output=True, text=True)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(name)))
        try:
            assert migrate('upgrade', 'b731c5ae204f').returncode == 0
            conn_url = test_url.set(drivername='postgresql').render_as_string(hide_password=False)
            wid, jid, aid, entry = [uuid4() for _ in range(4)]
            with psycopg.connect(conn_url) as db:
                db.execute("INSERT INTO coordinator.workers (id,name,hostname,cpu,cpu_cores,ram_gb,supported_tasks,benchmark_score,cpu_utilization,memory_utilization,active_tasks) VALUES (%s,'legacy','host','cpu',1,8,'[\"sentiment-classification\"]',1,0,0,0)", (wid,))
                db.execute("INSERT INTO coordinator.jobs (id,task_type,optimization,total_inputs,total_tasks) VALUES (%s,'sentiment-classification','fastest',1,1)", (jid,))
            assert migrate('upgrade', 'head').returncode == 0
            with psycopg.connect(conn_url) as db:
                assert db.execute('SELECT name,owner_account_id FROM coordinator.workers WHERE id=%s', (wid,)).fetchone() == ('legacy', None)
                assert db.execute('SELECT total_inputs,owner_account_id FROM coordinator.jobs WHERE id=%s', (jid,)).fetchone() == (1, None)
                for table in ('accounts','credentials','wallets','credit_entries','provider_policies','execution_attempts'):
                    assert db.execute('SELECT relrowsecurity FROM pg_class WHERE oid=to_regclass(%s)', ('coordinator.'+table,)).fetchone()[0]
                db.execute("INSERT INTO coordinator.accounts (id,name) VALUES (%s,'test')", (aid,))
                db.execute("INSERT INTO coordinator.credit_entries (id,account_id,kind,available_delta,reserved_delta,idempotency_key) VALUES (%s,%s,'grant',10,0,'migration-test')", (entry,aid))
            for statement in ('UPDATE coordinator.credit_entries SET available_delta=20',
                              'DELETE FROM coordinator.credit_entries', 'TRUNCATE coordinator.credit_entries'):
                with psycopg.connect(conn_url) as db, pytest.raises(psycopg.errors.RaiseException, match='append-only'):
                    db.execute(statement)
            assert migrate('downgrade', 'b731c5ae204f').returncode != 0
            with psycopg.connect(conn_url) as db:
                assert db.execute('SELECT available_delta FROM coordinator.credit_entries WHERE id=%s', (entry,)).fetchone()[0] == 10
        finally:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
