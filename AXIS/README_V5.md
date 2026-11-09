# VECTOR Brain V5

This extends V4 with (1) an interactive visualization of a small neural network's weights (this untrained V5 example has been replaced; see README_V6.md); (2) Docker-based isolated syntax/unittest verification; (3) explicit human-approved, allowlisted Python module updates with backups and rollback.

## Windows 11

1. Install Python 3.11+, Docker Desktop with Linux containers, and optionally Ollama for the V4 features.
2. Open PowerShell in this directory: `py -m pip install -r requirements.txt`.
3. PyTorch is optional and not needed for the 3D view (see README_V6.md).
4. For isolated tests, start Docker Desktop and pre-pull `docker pull python:3.12-slim` while online.
5. Run `py server.py` and visit `http://127.0.0.1:8765`.
6. Click **Gerçek sinir ağı** to view weights, rotate/zoom. Green lines = positive weights; pink = negative; thickness = magnitude.
7. In Self-Evolution V5, submit a Python module change, inspect diff, run Docker test, approve explicitly, then restart VECTOR. Rollback requires separate confirmation and restart.

## Important limitations

- The 3D neural view is a small trained XOR network (2→8→1), not Qwen3's billions of weights. The former untrained 4→8→6→2 PyTorch example no longer exists. See README_V6.md.
- Docker isolation is defense in depth, **not an absolute security guarantee**. Docker Desktop must be trusted and patched. No host-side execution fallback is allowed.
- The Docker test currently checks Python syntax and discovers any `test_*.py` in the isolated staging directory. No behavior tests are automatically generated; therefore a passing result does **not** establish functional correctness. Review is mandatory.
- Only `vector_intelligence.py`, `research_extensions.py`, and `skills_helpers.py` are updateable. `server.py`, `vector_upgrade.py`, `self_evolution.py` and permission code are deliberately protected.
- Updates do not hot-reload; restart is required. Rollback restores only the target file, not external side effects or database migrations.
- LLM autonomous core proposal generation, real Qwen3 weight/activation visualization, and complete secure production-grade self-modification are **not implemented**.
- The previous V4 features may require network access, PyMuPDF, and a running Ollama model.

Run tests: `py -m unittest test_server.py test_v5.py -v`.