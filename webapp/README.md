# webapp — MetaAgent-Epi human-in-the-loop demo

End-to-end, reviewable systematic-review pipeline that wraps existing
`metaagent` modules as black-box job steps. Frontend and backend live here
together; they reuse the repo's `metaagent/` and `tools/` packages. Runtime
artifacts are written only to ignored local directories.

```
webapp/
├── app/          FastAPI backend (package name: `app`)
│   ├── main.py   app + CORS + /health
│   ├── runs.py   run/step/event REST + SSE
│   ├── steps/    5 pipeline steps wrapping metaagent
│   └── ...       db.py models.py events.py schemas.py
├── frontend/     Vite + React 19 + Tailwind v4 + shadcn/ui
├── run-backend.sh
└── run-frontend.sh
```

## Run (two terminals)

```bash
# 1) backend on :8000  (must run from repo root cwd — the script handles it)
webapp/run-backend.sh

# 2) frontend on :5173  (proxies /api -> :8000)
webapp/run-frontend.sh
```

Then open http://127.0.0.1:5173

## Why the backend runs from the repo root

`metaagent` is not pip-installed and artifact paths are relative
(`data/runs/...`). `run-backend.sh` therefore `cd`s to the repo root, exports
`PYTHONPATH=<repo root>`, and uses `uvicorn --app-dir webapp` so the `app`
package is importable while cwd stays at the repo root. Runtime output and the
SQLite DB are written under `<repo root>/data/` (git-ignored).

## Regenerate the typed API client

With the backend running:

```bash
cd webapp/frontend && pnpm openapi-ts
```
