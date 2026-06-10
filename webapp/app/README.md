# MetaAgent-Epi Pipeline Demo Backend

This is a minimal, self-contained FastAPI backend harness for the step-1
human-in-the-loop pipeline demo. It does not import or run the real
`metaagent/` modules yet.

## Run

```bash
.venv/bin/uvicorn app.main:app --reload --port 8000
```

## Try the demo

Create a run:

```bash
RUN_ID=$(
  curl -s -X POST http://127.0.0.1:8000/runs \
    -H 'Content-Type: application/json' \
    -d '{"params":{"demo":true}}' \
  | .venv/bin/python -c 'import json, sys; print(json.load(sys.stdin)["id"])'
)
echo "$RUN_ID"
```

In one terminal, stream events:

```bash
curl -N "http://127.0.0.1:8000/runs/$RUN_ID/events"
```

In another terminal, start the demo step:

```bash
curl -s -X POST "http://127.0.0.1:8000/runs/$RUN_ID/steps/1/start"
```

The event stream replays existing events first, then streams live stdout
captured from the demo step.

