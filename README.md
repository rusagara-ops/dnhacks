# Stranded Compute

One repository for the backend, worker, and frontend.

## Structure

- `backend/`: API, orchestration, and persistence. Primary area owned by Codex.
- `worker/`: compute job execution and worker lifecycle.
- `frontend/`: user interface and backend API integration.

Each component keeps its source, tests, dependencies, and setup instructions inside its own directory. Frameworks and runtimes are not chosen yet.

## Collaboration

Use short-lived feature branches and focused pull requests. Keep component-specific changes within the relevant directory. Coordinate changes to API contracts, job payloads, and root configuration with affected contributors before merging. Document agreed contracts in `backend/` and link to them from worker and frontend documentation.
