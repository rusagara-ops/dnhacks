# Controlled compute sharing implementation plan

Base: `origin/main` at `770601b`. Work on `kevin/controlled-compute-sharing`.

## Scope and compatibility

- Keep existing demo authentication and job/worker flows as the default (`AUTH_MODE=demo`). Add explicit `AUTH_MODE=controlled`, requiring individual account/worker credentials, with the configured API token reserved for administrative setup. Never silently open controlled mode without authentication.
- Accounts are administrator-enrolled members (can buy and provide compute) or administrators. Tokens are shown once, stored hashed, individually revocable, and scoped to account operations or a specific worker installation. No passwords, cash, external payouts, or arbitrary submitted program execution in this release.
- Add owner IDs to jobs and workers. Enforce ownership on reads and writes, including results, activity, registration, heartbeat, and completion. Identifiers alone do not authorize access.
- Provider policy: pause/resume new assignments, allowed task types, maximum concurrency, minimum free RAM, and optional recurring UTC availability windows. Existing assignments drain normally. This is admission control, not OS/GPU sandbox enforcement.
- Demo credits: quote before submission, atomic reservation, one settlement per accepted task, refund permanently failed work, and append-only accounting records. Charge bounded inputs rather than self-reported run times. Existing demo jobs remain unmetered.
- Reliability: record assignment outcomes going forward; report accepted completions, failures/expired assignments, and separately labeled reported execution time. No security certification, historic attribution reconstruction, or latency claim.
- Add a dashboard for provider controls, accounts/credential enrollment, credit balances/history, and reliability. Support the existing React dashboard; keep the demo server workflow usable on Abel's Mac.

## Parallel ownership

1. Authentication agent: account/credential models, security dependency, account APIs, ownership enforcement on existing routes, focused tests.
2. Ledger agent: wallet/ledger models, quote and credit APIs, transaction-safe service hooks, focused tests. Parent integrates lifecycle hooks.
3. Frontend agent: controlled-sharing UI and frontend tests/docs, using the API contracts agreed in the agent messages.
4. Parent: provider policies, scheduler/lifecycle integration, migration, reliability, worker enrollment UX, end-to-end verification, rollout documentation and PR.

## Verification and rollout

Use disposable local PostgreSQL databases only. Verify migrations on existing rows, all existing backend/worker tests, new ownership and credit lifecycle tests, frontend tests/build, and browser coverage. No real payments or real GPU benchmark claims. Document migration/configuration/rollback and worker enrollment steps for Abel; do not deploy changes to his machine remotely. Push a review branch and PR after checks, without merging.

## Implementation outcome

All four work areas are implemented. The shared dashboard is at
`/demo/sharing.html`, linked from both job dashboards. Controlled submissions show
a quote and require explicit confirmation; the backend independently reserves
credits. See [CONTROLLED_COMPUTE.md](CONTROLLED_COMPUTE.md) for the supported
workflow, trust boundaries, and rollout steps.

Verification completed: 162 backend tests (including a generated-database
migration rehearsal), 27 worker tests, 8 TypeScript tests, 3 distribution tests,
16 browser tests, and the frontend production build passed. Two optional real-GPU
backend tests were skipped. Additional targeted checks cover the final provider
eligibility messages. Existing test fixtures were updated for new owner foreign
keys and the preceding main branch's model-slot column without weakening their
transaction rollback or RLS assertions.
