# Ronald's local UI testing setup

This setup runs the real coordinator and PostgreSQL with a **simulated worker**. Results are fabricated fixtures, not real model inference. No connection to Abel or Supabase is needed.

Current local settings are in ignored `backend/.env`: database at `127.0.0.1:55432`, model `simulation/ui`, revision `v1`, no API token. Keep the backend bound to loopback with this configuration.

From the repository root, restart the database if it is stopped:

```sh
/opt/homebrew/bin/pg_ctl -D /private/tmp/dnhacks-ronald-pg -l /private/tmp/dnhacks-ronald-pg.log -o '-h 127.0.0.1 -p 55432 -k /private/tmp' start
```

Database files are in `/private/tmp/dnhacks-ronald-pg`; they survive process restarts but the OS may clear temporary storage. This is disposable test data.

Start the backend in a terminal:

```sh
cd backend
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the simulator in another terminal:

```sh
cd backend
.venv/bin/python -m scripts.simulated_worker --ui-modes --name Local-UI-SIMULATION --delay 3 --idle-timeout 86400 --max-tasks 100000
```

Run `npm run dev` from `frontend/`. In the frontend, connect to `http://127.0.0.1:8000` and leave the token empty. API docs: `http://127.0.0.1:8000/docs`.

All four document/code modes and legacy sentiment can complete locally. The worker advertises simulated hardware, produces labeled fixture outputs, and takes approximately three seconds per task. Jobs still use the real assignment, heartbeat, persistence, and result APIs. The initial four smoke-test jobs are retained for reopening in Recent jobs.

For failure testing, stop the ordinary simulator first and run it with `--fail-tasks`. For recovery testing, use `--crash-after-claim`, then restart the ordinary simulator; coordinator recovery requeues unfinished work. Each simulator start creates a new worker registration, so old simulated workers can appear offline.

Stop the backend and simulator with Ctrl+C in their terminals. Stop this database with:

```sh
/opt/homebrew/bin/pg_ctl -D /private/tmp/dnhacks-ronald-pg stop -m fast
```

Real AI outputs require a real worker and matching model configuration. Do not treat these fixtures as inference-quality tests.
