import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  Activity,
  BookOpen,
  Check,
  ChevronRight,
  FileCode2,
  FileText,
  FlaskConical,
  History,
  LoaderCircle,
  PanelRightClose,
  Play,
  Plus,
  Save,
  Settings2,
  X,
} from "lucide-react";
import { load } from "js-yaml";
import { body, labelStatus, request } from "./api";
import type {
  Artifact,
  Mode,
  ReviewPatch,
  RunDetail,
  RunSummary,
  TaskDetail,
  TaskSummary,
} from "./api";
import { active } from "./utils";
import { Empty, ErrorMessage } from "./components/ui";
import { TaskEditor } from "./components/TaskEditor";
import {
  StageInspector,
  HistoryPanel,
  RunPanel,
  FilePanel,
} from "./components/RunWorkspace";
import { ReviewDrawer } from "./components/ReviewDrawer";
import { ArtifactDrawer } from "./components/ArtifactDrawer";
import { SettingsPanel } from "./components/SettingsPanel";

export default function App() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<TaskDetail | null>(null);
  const [dirty, setDirty] = useState(false);
  const [invalidEditors, setInvalidEditors] = useState<Record<string, boolean>>(
    {},
  );
  const pendingHistoryRun = useRef<string | null>(null);
  const [view, setView] = useState<"tasks" | "history" | "settings">("tasks");
  const [pane, setPane] = useState<"plan" | "run" | "files">("plan");
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [pollVersion, setPollVersion] = useState(0);
  const [mode, setMode] = useState<Mode>("end_to_end");
  const [input, setInput] = useState("");
  const [limit, setLimit] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [inspector, setInspector] = useState(true);
  const [review, setReview] = useState<ReviewPatch | null>(null);
  const [inspectArtifact, setInspectArtifact] = useState<Artifact | null>(null);
  const reduced = useReducedMotion();
  const refresh = useCallback(async () => {
    const [t, r] = await Promise.all([
      request<{ tasks: TaskSummary[] }>("/tasks"),
      request<{ runs: RunSummary[] }>("/runs"),
    ]);
    setTasks(t.tasks);
    setHistory(r.runs);
  }, []);
  useEffect(() => {
    let live = true;
    void Promise.all([
      request<{ tasks: TaskSummary[] }>("/tasks"),
      request<{ runs: RunSummary[] }>("/runs"),
    ])
      .then(([t, r]) => {
        if (live) {
          setTasks(t.tasks);
          setHistory(r.runs);
          if (t.tasks.length) setSelected(t.tasks[0].id);
        }
      })
      .catch((e) => {
        if (live) setError(String(e.message));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    if (!selected) return;
    let live = true;
    void request<TaskDetail>(`/tasks/${selected}`)
      .then((t) => {
        if (live) {
          setDraft(t);
          setDirty(false);
          setRunId(pendingHistoryRun.current ?? t.latest_run?.id ?? null);
          pendingHistoryRun.current = null;
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [selected]);
  useEffect(() => {
    if (!runId) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await request<RunDetail>(`/runs/${runId}`);
        if (live) {
          setRun(r);
          if (active(r.status)) timer = setTimeout(poll, 2500);
          else void refresh().catch(() => {});
        }
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : String(e));
      }
    };
    void poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [runId, pollVersion, refresh]);
  async function action(name: string, fn: () => Promise<void>) {
    setBusy(name);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }
  function chooseTask(id: string) {
    if (dirty && !window.confirm("当前编辑尚未保存，确定切换任务？")) return;
    setInvalidEditors({});
    setSelected(id);
    setRun(null);
    setRunId(null);
    setPane("plan");
    setView("tasks");
    setError("");
  }
  async function newTask() {
    if (dirty && !window.confirm("当前编辑尚未保存，确定新建任务？")) return;
    await action("new", async () => {
      const t = await request<{
        name: string;
        task_yaml: string;
        codebook_yaml: string;
      }>("/templates/default");
      setInvalidEditors({});
      setSelected(null);
      setRun(null);
      setRunId(null);
      setDraft({ ...t, id: "", created_at: "", updated_at: "" });
      setDirty(true);
      setView("tasks");
      setPane("plan");
    });
  }
  function edit(changes: Partial<TaskDetail>) {
    if (draft) {
      setDraft({ ...draft, ...changes });
      setDirty(true);
    }
  }
  async function save() {
    if (!draft) return;
    if (Object.values(invalidEditors).some(Boolean)) {
      setError("协议 JSON 尚未修正，无法保存。");
      return;
    }
    await action("save", async () => {
      load(draft.task_yaml);
      load(draft.codebook_yaml);
      const data = await request<TaskDetail>(
        draft.id ? `/tasks/${draft.id}` : "/tasks",
        {
          ...body({
            name: draft.name,
            task_yaml: draft.task_yaml,
            codebook_yaml: draft.codebook_yaml,
          }),
          method: draft.id ? "PUT" : "POST",
        },
      );
      setDraft(data);
      setSelected(data.id);
      setDirty(false);
      setNotice("研究方案已保存");
      await refresh();
    });
  }
  async function start() {
    if (!draft?.id || dirty || Object.values(invalidEditors).some(Boolean)) {
      setError("请先保存研究方案，再开始运行。");
      return;
    }
    await action("run", async () => {
      const r = await request<RunDetail>(
        `/tasks/${draft.id}/runs`,
        body({
          mode,
          input_text: mode === "end_to_end" ? undefined : input,
          limit: limit ? Number(limit) : null,
          ablation: "full",
        }),
      );
      setRun(r);
      setRunId(r.id);
      setPollVersion((v) => v + 1);
      setPane("run");
      await refresh();
    });
  }
  async function resume() {
    if (!run) return;
    await action("resume", async () => {
      const r = await request<RunDetail>(`/runs/${run.id}/resume`, body({}));
      setRun(r);
      setRunId(r.id);
      setPollVersion((v) => v + 1);
      setPane("run");
      await refresh();
    });
  }
  async function cancel() {
    if (!run || !active(run.status)) return;
    await action("cancel", async () => {
      const value = await request<RunDetail>(`/runs/${run.id}/cancel`, {
        method: "POST",
      });
      setRun(value);
      setRunId(value.id);
      setPollVersion((v) => v + 1);
      setNotice("运行已停止，已有产物保留，可继续运行。");
      await refresh();
    });
  }
  async function upload(file: File) {
    if (!draft?.id) {
      setError("请先保存任务，再上传文件。");
      return;
    }
    await action("upload", async () => {
      const value = await request<{
        path: string;
        filename: string;
        sha256: string;
      }>(`/tasks/${draft.id}/files?filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      });
      setNotice(`已上传 ${value.filename}`);
      if (file.name.toLowerCase().endsWith(".jsonl")) {
        setInput(await file.text());
        setNotice(`已上传 ${value.filename} 并读取真实 JSONL 输入`);
      } else if (mode === "coding" && /\.(pdf|md|txt)$/i.test(file.name)) {
        const row = { record_id: file.name, path: value.path };
        setInput((old) =>
          old.trim()
            ? old.trim() + "\n" + JSON.stringify(row)
            : JSON.stringify(row),
        );
      } else if (
        ["jsonl", "csv", "ris"].includes(
          file.name.split(".").pop()?.toLowerCase() ?? "",
        )
      ) {
        setNotice(`已上传至 ${value.path}。JSONL 可直接填入模块输入。`);
      } else setNotice(`已上传：${value.path}`);
    });
  }
  async function openReview(artifact: string) {
    if (!run) return;
    await action("review", async () => {
      setReview(
        await request<ReviewPatch>(
          `/runs/${run.id}/review?artifact=${encodeURIComponent(artifact)}`,
        ),
      );
    });
  }
  const displayTitle =
    view === "settings"
      ? "模型与服务"
      : view === "history"
        ? "运行记录"
        : draft?.name || "研究工作台";
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="MetaAgent-Epi 首页">
          <FlaskConical size={24} />
          <span>
            MetaAgent<span className="brand-suffix">Epi</span>
            <small>文献与证据工作台</small>
          </span>
        </a>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          <button
            className={view === "tasks" ? "selected" : ""}
            onClick={() => setView("tasks")}
          >
            <BookOpen size={17} />
            研究任务<span>{tasks.length}</span>
          </button>
          <button
            className={view === "history" ? "selected" : ""}
            onClick={() => {
              setView("history");
              void refresh().catch((e) => setError(e.message));
            }}
          >
            <History size={17} />
            运行记录
          </button>
          <button
            className={view === "settings" ? "selected" : ""}
            onClick={() => setView("settings")}
          >
            <Settings2 size={17} />
            模型与服务
          </button>
        </nav>
        <div className="task-list-title">
          <span>最近研究</span>
          <button
            className="icon-button"
            title="新建研究"
            onClick={() => void newTask()}
          >
            <Plus size={16} />
          </button>
        </div>
        <div className="sidebar-tasks">
          {tasks.map((t) => (
            <button
              key={t.id}
              className={`task-nav ${selected === t.id ? "active" : ""}`}
              onClick={() => chooseTask(t.id)}
            >
              <span className={`task-dot ${t.latest_run?.status || ""}`} />
              <span>
                {t.name}
                <small>
                  {t.latest_run ? labelStatus(t.latest_run.status) : "尚未运行"}
                </small>
              </span>
            </button>
          ))}
          {!tasks.length && !loading && (
            <p className="sidebar-empty">尚未创建研究任务</p>
          )}
        </div>
        <label className="mobile-task-switcher">
          切换研究任务
          <select
            aria-label="移动端切换研究任务"
            value={selected ?? ""}
            disabled={!tasks.length}
            onChange={(event) => {
              if (event.target.value) chooseTask(event.target.value);
            }}
          >
            <option value="" disabled>
              {tasks.length ? "选择已保存的研究" : "暂无已保存研究"}
            </option>
            {tasks.map((task) => (
              <option key={task.id} value={task.id}>
                {task.name}
              </option>
            ))}
          </select>
        </label>
        <div className="sidebar-bottom">
          <span className="connection-dot" />
          本地研究工作区
          <small>Query → Screening → Coding A+B → Synthesis</small>
        </div>
      </aside>
      <main className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            研究工作区
            <ChevronRight size={13} />
            <span>{view === "tasks" ? "研究任务" : displayTitle}</span>
          </div>
          <button
            className="button small"
            onClick={() => void newTask()}
            disabled={!!busy}
          >
            <Plus size={15} />
            新建研究
          </button>
        </header>
        <div className="page-heading">
          <div>
            <div className="eyebrow">
              {view === "settings"
                ? "RUNTIME CONFIGURATION"
                : view === "history"
                  ? "EXECUTION HISTORY"
                  : "EVIDENCE WORKSPACE"}
            </div>
            <h1>{displayTitle}</h1>
            <p>
              {view === "settings"
                ? "为四个阶段独立设置模型，凭据保存在本地。"
                : view === "history"
                  ? "查看实际运行状态、失败原因与保留的产物。"
                  : "从研究问题到可追溯的筛选、提取与综合。"}
            </p>
          </div>
          {view === "tasks" && draft && (
            <div className="heading-actions">
              {dirty && <span className="unsaved">未保存</span>}
              <button
                className="button"
                onClick={() => void save()}
                disabled={
                  !!busy ||
                  active(run?.status) ||
                  Object.values(invalidEditors).some(Boolean)
                }
              >
                {busy === "save" ? (
                  <LoaderCircle className="spin" size={16} />
                ) : (
                  <Save size={16} />
                )}
                保存方案
              </button>
              <button
                className="button primary"
                onClick={() => void start()}
                disabled={
                  !!busy ||
                  active(run?.status) ||
                  Object.values(invalidEditors).some(Boolean)
                }
              >
                <Play size={15} />
                开始运行
              </button>
            </div>
          )}
        </div>
        {error && (
          <div className="feedback">
            <ErrorMessage error={error} />
            <button
              className="icon-button"
              onClick={() => setError("")}
              aria-label="关闭错误"
            >
              <X size={16} />
            </button>
          </div>
        )}
        {notice && (
          <div className="notice" role="status">
            <Check size={16} />
            {notice}
            <button
              className="icon-button"
              onClick={() => setNotice("")}
              aria-label="关闭通知"
            >
              <X size={16} />
            </button>
          </div>
        )}
        <AnimatePresence mode="wait">
          <motion.div
            key={view}
            className="view-content"
            initial={{ opacity: 0, y: reduced ? 0 : 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduced ? 0 : 0.16 }}
          >
            {view === "settings" ? (
              <SettingsPanel
                action={action}
                busy={busy}
                onSaved={() => setNotice("运行配置已保存")}
              />
            ) : view === "history" ? (
              <HistoryPanel
                runs={history}
                onOpen={(r) => {
                  setView("tasks");
                  setPane("run");
                  setRunId(r.id);
                  setPollVersion((v) => v + 1);
                  if (r.task_id !== selected) {
                    pendingHistoryRun.current = r.id;
                    setSelected(r.task_id);
                  }
                }}
              />
            ) : loading ? (
              <div className="loading">
                <LoaderCircle className="spin" />
                正在连接研究工作区…
              </div>
            ) : !draft ? (
              <Empty
                title="开始一项研究"
                description="创建研究问题，定义纳排标准与分析协议，随后运行完整 A＋B 流程。"
              >
                <button
                  className="button primary"
                  onClick={() => void newTask()}
                >
                  <Plus size={16} />
                  新建研究
                </button>
              </Empty>
            ) : (
              <>
                <div className="workspace-tabs" role="tablist">
                  {(
                    [
                      { key: "plan", label: "研究方案", icon: FileCode2 },
                      { key: "run", label: "运行与结果", icon: Activity },
                      { key: "files", label: "文件与证据", icon: FileText },
                    ] as const
                  ).map((tab) => (
                    <button
                      role="tab"
                      aria-selected={pane === tab.key}
                      key={tab.key}
                      className={pane === tab.key ? "active" : ""}
                      onClick={() => setPane(tab.key)}
                    >
                      <tab.icon size={16} />
                      {tab.label}
                    </button>
                  ))}
                  <button
                    className="inspector-toggle icon-button"
                    onClick={() => setInspector(!inspector)}
                    title={inspector ? "收起阶段面板" : "展开阶段面板"}
                  >
                    <PanelRightClose size={17} />
                  </button>
                </div>
                <div className={`workspace ${inspector ? "" : "no-inspector"}`}>
                  <div className="workspace-main">
                    {pane === "plan" ? (
                      <TaskEditor
                        key={draft.id || "new"}
                        draft={draft}
                        onInvalid={(field, invalid) =>
                          setInvalidEditors((old) => ({
                            ...old,
                            [field]: invalid,
                          }))
                        }
                        onEdit={edit}
                        mode={mode}
                        setMode={setMode}
                        input={input}
                        setInput={setInput}
                        limit={limit}
                        setLimit={setLimit}
                        upload={upload}
                        busy={!!busy}
                      />
                    ) : pane === "run" ? (
                      <RunPanel
                        run={run}
                        busy={busy}
                        onResume={() => void resume()}
                        onCancel={() => void cancel()}
                        onArtifact={setInspectArtifact}
                        onReview={openReview}
                      />
                    ) : (
                      <FilePanel
                        draft={draft}
                        artifacts={run?.artifacts ?? []}
                        upload={upload}
                        onArtifact={setInspectArtifact}
                        busy={!!busy}
                      />
                    )}
                  </div>
                  {inspector && <StageInspector run={run} />}
                </div>
              </>
            )}
          </motion.div>
        </AnimatePresence>
      </main>
      {review && run && (
        <ReviewDrawer
          runId={run.id}
          initial={review}
          onClose={() => setReview(null)}
          onSaved={() => {
            setReview(null);
            setNotice("修订已提交；受影响的下游产物需要续跑");
            setPollVersion((v) => v + 1);
          }}
        />
      )}
      {inspectArtifact && (
        <ArtifactDrawer
          artifact={inspectArtifact}
          onClose={() => setInspectArtifact(null)}
        />
      )}
    </div>
  );
}
