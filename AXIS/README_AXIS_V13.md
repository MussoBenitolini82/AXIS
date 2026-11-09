# AXIS V13 — audited agent pipeline and learning dashboard

- `GET /api/axis-v13-dashboard`: standardized events, lessons, and graph nodes/edges.
- `POST /api/axis-v13-develop` `{ "request": "...", "target": "research_extensions.py" }`: existing planner/coder/reviewer/test-planning workflow, audited as a task.
- `POST /api/axis-v13-repair` `{ "error": "...", "target": "research_extensions.py" }`: guarded correction proposal; **does not deploy**.
- `POST /api/axis-v13-models` `{ "request": "..." }`: static curated model suggestions; **does not download**.

Every POST request is recorded as a redacted outcome event. The dashboard shows a task/agent/lesson graph. Existing approval-gated Docker tests remain the only path to apply generated code. The LLM role pipeline is sequential and not guaranteed to fix errors. Model recommendations are not a live model registry. This version is a bounded prototype, not autonomous self-modification.

Run tests: `cd AXIS && python -m unittest discover -p 'test*.py' -v`.