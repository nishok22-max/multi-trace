# TRACE

Traceable Reasoning Across Cross-modal Evidence: one inspectable state per case from text, PDFs, photos, tables and sensor series. Hackathon: TECHgium 10th edition, PID TG0906436.

Read `AGENTS.md` / `CLAUDE.md` first, then `docs/IMPLEMENTATION_PLAN.md`. Status: **M0 scaffold only, no business logic.**

## Native Windows setup (PowerShell)

Prerequisites (install by hand):

1. Python 3.11 (`winget install Python.Python.3.11`). The project pins `>=3.11,<3.12`.
2. uv (`winget install astral-sh.uv`).
3. Node 20 LTS (`winget install OpenJS.NodeJS.LTS`, or nvm-windows for version 20).
4. Git, then `git config core.longpaths true` and enable Windows long paths.
5. Tesseract 5 (`winget install UB-Mannheim.TesseractOCR`). Set `TRACE_TESSERACT_CMD` to the full path of `tesseract.exe`.
6. Copy `.env.example` to `.env` yourself if you need local overrides. Never commit `.env`.

Then, from the repo root:

```powershell
cd backend
uv sync
uv run python -m tools.task smoke-native
cd ../frontend
npm ci --ignore-scripts
npm run build
cd ../backend
uv run python -m tools.task check
uv run uvicorn trace_api.main:app --host 127.0.0.1 --port 8000
```

`make` is optional on Windows. Every target is `uv run python -m tools.task <name>` (run from `backend/`); the `Makefile` only wraps these.

Place the Microsoft dataset CSVs by hand in `seed/dataset/` (see `seed/dataset/README.md`). The app makes zero network calls at runtime.

Note: the dev proxy sends `/api` to `http://127.0.0.1:8000`.

## TODO

- TODO: Docker image, compose and `make smoke` (image) come later (not part of M0).
