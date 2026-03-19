# Workbench

Local visualization and analysis layer for `literature_search` and `coding_sheet`.

## Stack

- Backend: FastAPI
- Frontend: React + Vite
- UI: Tailwind with shadcn-style components
- Charts: ECharts

## Structure

```text
dev/workbench/
  backend/
  frontend/
  scripts/ops/
```

The backend is intentionally thin and read-only. It scans local manifests and outputs and exposes a stable JSON layer for the frontend.

## Run

From `dev/workbench/scripts/ops`:

```powershell
.\run_workbench.ps1
```

The combined launcher waits for both local ports to become ready before opening the frontend in your browser.

Or start each side separately:

```powershell
.\run_workbench_backend.ps1
.\run_workbench_frontend.ps1
```

If you use a local proxy tool, make sure `localhost`, `127.0.0.1`, and `::1` are bypassed. The provided PowerShell scripts now export `NO_PROXY` automatically for local workbench ports.
