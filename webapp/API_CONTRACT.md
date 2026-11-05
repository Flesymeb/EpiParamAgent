# Web workspace contract

Developer ownership: backend agent owns webapp/app, frontend agent owns webapp/frontend; coordinator owns this contract, scripts/docs and packaging. Archive is read-only reference; active webapp is restored at repository root. Use existing React/Vite and FastAPI libraries. Bind localhost by default and use Vite /api proxy. All responses JSON unless artifact/raw upload.

## Public shapes
TaskSummary: {id,name,created_at,updated_at,latest_run?:RunSummary|null}
TaskDetail: TaskSummary + {task_yaml,codebook_yaml}
RunSummary: {id,task_id,name,mode,status,created_at,updated_at,stage_results:object,error?:string|null}
RunDetail: RunSummary + {manifest:object|null,artifacts:[{key,name,size,media_type,url}],log:string}
status: queued,running,complete,partial,failed,interrupted. Never map partial/failed to success. Normal Coding always full A+B; no silent ablation. An explicit advanced ablation may be supported.

## Routes
- GET /api/health -> {status,version}
- GET /api/templates/default -> {name,task_yaml,codebook_yaml} (real editable template, no credentials)
- GET /api/config -> {modules:{query:Runtime,screening:Runtime,coding:Runtime,synthesis:Runtime},mineru:object,sources:object}; Runtime has provider,model,api_base,thinking,timeout_s,max_tokens,api_key_configured boolean. Never return any actual secret. POST /api/config takes {modules:{...},mineru?:...}; optional api_key writes privately, blank means retain. Merge existing configuration rather than clear unspecified fields. Keys never go in tasks, logs or responses.
  An explicitly submitted thinking:null clears only the private override and inherits the environment. Changing provider isolates the previous provider's identity and credentials.
- GET /api/tasks -> {tasks:TaskSummary[]}
- POST /api/tasks {name,task_yaml,codebook_yaml} -> TaskDetail (validate ReviewTask/review/analysis/codebook, managed task/codebook files)
- GET /api/tasks/{id} -> TaskDetail
- PUT /api/tasks/{id} same create fields -> TaskDetail (preserve previous revision; reject editing during active run)
- POST /api/tasks/{id}/files?filename=... raw binary body -> {filename,path,sha256}; safe managed path; PDF/MD/TXT/JSONL/CSV/RIS; bounded size. Refer to returned path in standalone input JSONL. UI upload works without multipart dependency.
- POST /api/tasks/{id}/runs {mode:'end_to_end'|'screening'|'coding'|'synthesis',input_text?:string,resume?:boolean,limit?:number|null,ablation?:'full'|'without_a'|'without_b'} -> RunDetail (202). Default full, no limit unless explicit. Module mode input JSONL: screening records, coding document manifest, synthesis estimates. Use exactly core WorkflowOptions/engines; no old parallel step logic. Backend may reject malformed inputs with actionable 422.
- GET /api/runs -> {runs:RunSummary[]}
- GET /api/runs/{id} -> RunDetail (polling sufficient; live log bounded tail, no fake progress). Include workflow six stages retrieval,screening,fulltext_fetch,fulltext_screening,coding,pooling with actual A/B coverage where available.
- POST /api/runs/{id}/resume -> RunDetail (202), same saved inputs/config, successful stage reuse by core hashes; prevent duplicate active execution.
- POST /api/runs/{id}/cancel -> RunDetail, stop only the identified managed worker process group, mark interrupted and retain partial artifacts for resume. Completed runs are not cancelled.
- GET /api/runs/{id}/artifacts/{key} -> file, only manifest-declared run artifacts, safe paths; support download query. UI uses returned artifact.url, not absolute filesystem paths.
- GET /api/runs/{id}/review?artifact=screening_predictions|fulltext_predictions|coding_estimates -> core export_review payload
- POST /api/runs/{id}/review {artifact,patch} -> core apply_review receipt (immutable predictions; reviewer/reason required; stale conflicts preserved)

Errors: {detail:string|object}; no raw secrets/tracebacks to client. Persist task/run metadata across backend restarts. Mark interrupted jobs honestly after server restart. Build production frontend can be served by backend at / when dist exists. Browser empty states, errors, pending reviews and unavailable scientific results must remain explicit.

Lifecycle: importing/constructing an app does not reconcile or signal jobs. Actual ASGI lifespan acquires the workspace's non-inheritable exclusive server.lock before orphan recovery; a second active owner fails without affecting existing jobs. Release the lease on shutdown. Use one backend instance per workspace.
