# Controlled compute sharing

The coordinator can run an approved-member compute pool with provider controls,
separate credentials, and demo-credit accounting. This is a demonstration economy:
credits have no cash value, withdrawals, or external payment integration.

## Keep Abel's existing demo available

The default `AUTH_MODE=demo` preserves shared-token access and unmetered jobs.
Run the new controlled demonstration with a **separate database** and, if running
both simultaneously, a separate coordinator port/configuration. Both can live on
Abel's Mac; model weights stay on their actual worker machines. Kevin does not
need to download Gemma merely to develop the backend or view the dashboard.

Do not run migrations, change tokens, or restart Abel's process from another
computer without coordinating the rollout. These instructions are for the host.

1. Preserve local work, fetch this PR branch, and install the existing backend
   requirements into the existing Python environment. No new backend packages
   or frontend build are needed for `/demo/` and `/demo/sharing.html`.
2. Back up the database, change into `backend/`, and run
   `.venv/bin/python -m alembic upgrade head`.
   Migration `c84d12e6a901` follows `b731c5ae204f` and adds accounts, credentials,
   owner links, wallets/ledger, provider policies, and attempt history. Existing
   workers/jobs retain their IDs and results; their owner is initially unset.
3. For the separate controlled instance set `AUTH_MODE=controlled`, its own
   `DATABASE_URL`, and a private random `API_TOKEN` for administrator setup. Keep
   the existing model/digest configuration. Without a valid credential controlled
   mode always rejects API access, even when `API_TOKEN` is unset.
4. Serve the app and coordinator through trusted HTTPS for network use. Both
   browser and worker connections need encryption. This change does not provision
   certificates or encrypt plain HTTP. Keep the database schema private and use
   the existing backend database owner/service role; all new tables enable RLS
   and revoke PUBLIC access just like the existing coordinator tables.
5. Restart the intended backend process and check `/health`, `/ready`, and
   `/demo/sharing.html`. A static-file update alone does not load new API routes.

Once a database contains individual accounts, startup refuses `AUTH_MODE=demo`.
This prevents an accidental mode change from exposing member jobs under the
shared demo key. Keep using the separate legacy demo database for the old flow.
Never point simultaneous demo and controlled processes at the same database;
the mode check runs at startup.

## First accounts and provider enrollment

1. Open `/demo/sharing.html` on the controlled coordinator. Enter the setup token
   privately, create an administrator account, and save the returned account
   token. It is shown once; the database stores only a hash. Reconnect using the
   administrator account token for normal administration and jobs.
2. Create approved member accounts and give their account tokens to their owners
   through a private channel. A member can both consume and provide compute.
   Administrator grants create explicitly labeled demo credits. Retrying the same
   grant request ID cannot grant twice. No purchase or payout occurs.
3. On a provider machine, from the updated repository root, run:

   ```zsh
   worker/.venv/bin/python worker/run.py --show-device-id
   ```

   This exits before loading a model. The identifier is for enrollment, not a
   credential. The current Mac implementation derives a stable application ID
   from the hardware UUID without transmitting the raw hardware UUID.
4. Sign in to the sharing dashboard with that provider's account token. Under
   **Worker access**, use the installation ID to issue a worker credential. Save
   it privately. If the worker already exists as an unowned demo row in this
   database, an administrator must explicitly adopt the idle worker first. Owned
   workers cannot be transferred to another account through this endpoint.
5. Start the normal local Ollama server and install the exact agreed model. Enter
   the **worker credential**, not the account or setup token, into the terminal:

   ```zsh
   unsetopt XTRACE VERBOSE
   read -s "API_TOKEN?Worker credential: "
   echo
   export API_TOKEN
   worker/.venv/bin/python worker/run.py \
     --url https://YOUR_COORDINATOR \
     --name Kevin-Mac \
     --models qwen2.5-coder:3b \
     --scoped-credential
   unset API_TOKEN
   ```

   `--scoped-credential` omits automatic migration of older installation aliases.
   It preserves the original behavior when absent for existing demo launchers.
   Normal worker GPU/model checks still apply. Qwen supports coding assistance;
   use an agreed compatible Gemma worker for the other inference modes.
6. Newly owned machines start **paused**. In **Your compute machines**, review the
   permitted workload types, concurrency, free-memory threshold, and optional
   UTC schedule, then enable sharing. Registration retries do not reset policy.

Revocation blocks the credential's next request, including result uploads. Pause
and drain a worker before revoking it when practical. Administrators can list
and revoke an account's credentials or issue a replacement account token without
losing its identity, workers, jobs, or credits. Issuing a replacement does not
implicitly revoke old keys; revoke compromised keys explicitly.

## What the controls enforce

- Pause, schedule, workload permissions, minimum available RAM, and concurrency
  are checked before **new** assignments. In-flight assignments remain valid and
  can complete. The worker row lock orders policy changes against new claims.
- The concurrency cap is 1 or 2 assignments, matching the current model slots.
  The scheduler counts assignments, rather than trusting a reported active count.
- Schedules are recurring UTC windows: Monday=0 through Sunday=6; start is
  inclusive and end exclusive. Empty windows mean any time. Split an overnight
  window at midnight. No local-time/daylight-saving conversion is implied.
- A positive minimum free-RAM threshold blocks new work if free RAM is unknown.
  It is admission control, not a hard OS memory limit, a GPU reservation, or
  automatic detection of keyboard/mouse inactivity. The owner explicitly enables
  sharing and may choose a schedule.
- Work remains predefined text inference. This feature does not execute customer
  code, run arbitrary containers, or add a host sandbox. Ollama stays native on
  Apple Silicon to retain its supported GPU execution path.

## Credit and reliability semantics

The quote is one demo credit per bounded input (`demo-v1`). Job creation reserves
the whole amount in the same transaction as creating its tasks. An insufficient
balance returns 402 and creates no job. A successful accepted task spends its
reserved inputs and credits the enrolled provider once. Worker-reported time,
hardware, and token counts never determine the charge. Legacy unowned jobs are
unmetered; unenrolled machines cannot claim metered jobs.

Retries keep the reservation. A permanently failed task returns its reservation,
while successful partial results and their earnings remain. Completion retries
cannot pay twice; stale assignments cannot complete. If a job has no compatible
available provider, it remains queued with credits reserved; this release does
not implement job cancellation or automatic refunds for waiting time.

Balances and immutable ledger entries update atomically under ordered wallet
locks. Database triggers reject ledger UPDATE, DELETE, and TRUNCATE; database
administrators remain trusted and can alter the database itself. Self-owned work
does not grow the spendable balance, but counts toward cumulative earned/activity
totals. Those totals are not an independent reputation or profitability measure.

Reliability counts assignment outcomes recorded **after this feature starts**:
accepted completions, reported failures, expired assignments, and observed
assignments (including currently active ones). Historical retry ownership is not
invented. Average successful execution time is worker-reported, excludes queue
and network time, and is neither verified model quality nor a security rating.

## Trust boundary

Account credentials access their own jobs/results and their own provider controls;
administrators deliberately have broader access. Worker keys can register only
their bound installation and operate its assignments. Public worker inventory
is visible to approved members, but a worker key cannot browse jobs, balances,
or administrative APIs. Discovery does not prove a machine or model is honest.

Providers and the coordinator can inspect input text they process. HTTPS protects
transit, not data from the host administrator. Use only approved providers and
data they are permitted to handle. Credentials are revocable bearer secrets, not
hardware attestation; stealing a worker credential still permits impersonation of
that installation until revocation. No passwords, public self-signup, rate-limiter,
confidential-computing hardware, or external payout system is introduced here.

## Verification and rollback

Backend tests use disposable local PostgreSQL. From `backend/`:

```zsh
TEST_DATABASE_URL=YOUR_DISPOSABLE_LOCAL_DATABASE .venv/bin/python -m pytest tests -q
```

Run worker tests separately because existing backend/worker tests share module
names: `backend/.venv/bin/python -m pytest worker/tests -q` from the root. Set
`RUN_MIGRATION_TESTS=1` for the optional migration rehearsal; it creates/drops a
generated database on a local cluster with CREATE DATABASE permission. Frontend
tests/build and browser tests are documented in `frontend/README.md`. Simulated
tests verify accounting and ownership, not physical GPU performance or real cash.

To roll back a rehearsal, stop its new workers/coordinator and resume the existing
demo against its separate database. Preserve the controlled database for account
and ledger history. Downgrading the new migration refuses to drop a database's
sharing tables once accounts exist. Never discard account/credit records to make
an old version start; restore an appropriate backup into a separate database.
