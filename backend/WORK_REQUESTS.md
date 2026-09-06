# Provider-mediated work requests

The controlled demo now supports an opt-in approval lane without changing direct job submission.

1. A member opens `/demo/requests.html` and connects with an account token.
2. `GET /api/work-requests/providers` returns coarse capabilities for workers owned by other enabled accounts. It does not expose LAN addresses or credentials.
3. The member posts a task, model, provider account, and worker to `POST /api/work-requests`.
4. The provider sees incoming requests in `GET /api/work-requests` and approves or declines with `POST /api/work-requests/{id}/approve` or `/decline`.
5. The requester selects an approved request on `/demo/` and submits a matching job. The coordinator binds that job to the approved worker and consumes the request atomically.

Direct jobs remain unchanged when `work_request_id` is omitted. Existing provider policy, heartbeat, model, RAM, and concurrency checks still decide whether the worker can actually claim work. The additive migration is `f1b9c3d2e4a5_work_requests.py`; apply it before restarting a coordinator built from this branch.

Work request tokens are account credentials. Worker credentials remain installation-scoped and belong only in worker terminals.
