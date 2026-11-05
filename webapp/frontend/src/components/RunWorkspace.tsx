import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  ArrowDownToLine,
  ArrowRight,
  Check,
  ChevronDown,
  FileText,
  LoaderCircle,
  RefreshCw,
  Square,
  Search,
  Upload,
  X,
} from "lucide-react";
import type { Artifact, RunDetail, RunSummary, TaskDetail } from "../api";
import { labelStatus, modeLabels } from "../api";
import { active, json, object, stages, time } from "../utils";
import { Empty, ErrorMessage, Status } from "./ui";
import { SynthesisSummary } from "./SynthesisSummary";

export function StageInspector({ run }: { run: RunDetail | null }) {
  const [expanded, setExpanded] = useState<string | null>("coding");
  const reduced = useReducedMotion();
  const stagesData = {
    ...object(run?.manifest?.stage_results),
    ...object(run?.stage_results),
  };
  return (
    <aside className="stage-inspector">
      <div className="inspector-heading">
        <span>阶段检查</span>
        <span className="tiny-label">LIVE ARTIFACTS</span>
      </div>
      <div className="pipeline">
        {stages.map((stage, index) => {
          const data = object(stagesData[stage.key]);
          const status = String(data.status ?? "not_started");
          return (
            <div className={`pipeline-stage ${status}`} key={stage.key}>
              <button
                className="stage-button"
                onClick={() =>
                  setExpanded(expanded === stage.key ? null : stage.key)
                }
                aria-expanded={expanded === stage.key}
              >
                <span className="stage-marker">
                  {status === "complete" ? (
                    <Check size={13} />
                  ) : status === "running" ? (
                    <LoaderCircle className="spin" size={13} />
                  ) : status === "failed" ? (
                    <X size={13} />
                  ) : (
                    index + 1
                  )}
                </span>
                <span>
                  <strong>{stage.name}</strong>
                  <small>{stage.sub}</small>
                </span>
                <ChevronDown
                  size={13}
                  className={expanded === stage.key ? "rotated" : ""}
                />
              </button>
              <AnimatePresence initial={false}>
                {expanded === stage.key && (
                  <motion.div
                    className="stage-details"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: reduced ? 0 : 0.16 }}
                  >
                    <Status value={status} />
                    {data.reused === true && <p>已复用核验通过的阶段产物</p>}
                    {stage.key === "coding" &&
                      Array.isArray(data.actual_ab) &&
                      data.actual_ab.map((coverage, index) => {
                        const actual = object(coverage);
                        return (
                          <p key={index}>
                            文档{" "}
                            {String(
                              actual.record_id ??
                                actual.document_id ??
                                index + 1,
                            )}
                            <br />A 候选调用：
                            {String(actual.stage_a_calls ?? "未提供")}
                            <br />B 定稿调用：
                            {String(actual.stage_b_calls ?? "未提供")}
                            <br />
                            {labelStatus(String(actual.status ?? "pending"))}
                          </p>
                        );
                      })}
                    {data.unresolved !== undefined && (
                      <p>待核实 / 未解决：{String(data.unresolved)}</p>
                    )}
                    {data.stale === true && (
                      <p className="warning-text">
                        上游修订后已过期，需要重新运行
                      </p>
                    )}
                    {Boolean(data.error) && (
                      <p className="warning-text">
                        {typeof data.error === "string"
                          ? data.error
                          : json(data.error)}
                      </p>
                    )}
                    {!Object.keys(data).length && <p>运行后显示实际阶段信息</p>}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
      <div className="inspector-note">
        <FileText size={16} />
        <p>
          原始文献、模型预测与人工修订分别保留；最终综合以实际计算产物为准。
        </p>
      </div>
      {run && (
        <div className="run-meta">
          <span>RUN ID</span>
          <code>{run.id}</code>
          <span>最近更新</span>
          <p>{time(run.updated_at)}</p>
        </div>
      )}
    </aside>
  );
}

export function HistoryPanel({
  runs,
  onOpen,
}: {
  runs: RunSummary[];
  onOpen: (run: RunSummary) => void;
}) {
  const [filter, setFilter] = useState("");
  const visible = runs.filter((r) =>
    (r.name + " " + r.id + " " + r.status)
      .toLowerCase()
      .includes(filter.toLowerCase()),
  );
  return (
    <section className="history-panel">
      <div className="list-toolbar">
        <span>{runs.length} 次真实运行</span>
        <label className="search-field">
          <Search size={15} />
          <input
            aria-label="搜索运行"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="搜索名称、状态或 ID"
          />
        </label>
      </div>
      {!runs.length ? (
        <Empty
          title="还没有运行记录"
          description="保存研究方案并运行后，这里会保留阶段状态、日志和结果。"
        />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>研究 / 运行</th>
                <th>模式</th>
                <th>状态</th>
                <th>更新时间</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.id} onClick={() => onOpen(r)}>
                  <td>
                    <strong>{r.name}</strong>
                    <small className="mono">{r.id}</small>
                  </td>
                  <td>{modeLabels[r.mode] ?? r.mode}</td>
                  <td>
                    <Status value={r.status} />
                  </td>
                  <td>{time(r.updated_at)}</td>
                  <td>
                    <button
                      className="icon-button"
                      aria-label={`打开 ${r.name}`}
                    >
                      <ArrowRight size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function RunPanel({
  run,
  busy,
  onResume,
  onCancel,
  onArtifact,
  onReview,
}: {
  run: RunDetail | null;
  busy: string;
  onResume: () => void;
  onCancel: () => void;
  onArtifact: (artifact: Artifact) => void;
  onReview: (artifact: string) => Promise<void>;
}) {
  const [tab, setTab] = useState<"results" | "log" | "manifest">("results");
  if (!run)
    return (
      <Empty
        title="尚未开始运行"
        description="在研究方案中选择完整端到端或独立模块，然后开始运行。"
      />
    );
  const reviewable = run.artifacts.filter((a) =>
    [
      "screening_predictions",
      "fulltext_predictions",
      "coding_estimates",
    ].includes(a.key),
  );
  return (
    <div className="run-panel">
      <div className="run-overview">
        <div>
          <Status value={run.status} />
          <h2>{modeLabels[run.mode] ?? run.mode}</h2>
          <span className="mono muted">{run.id}</span>
        </div>
        {active(run.status) ? (
          <button className="button" disabled={!!busy} onClick={onCancel}>
            <Square size={14} />
            停止运行
          </button>
        ) : (
          <button
            className="button"
            disabled={active(run.status) || !!busy}
            onClick={onResume}
          >
            <RefreshCw size={15} />
            续跑 / 复用已完成阶段
          </button>
        )}
      </div>
      {run.error && (
        <ErrorMessage
          error={typeof run.error === "string" ? run.error : json(run.error)}
        />
      )}
      {run.status === "partial" && (
        <p className="status-message">
          部分阶段或输入仍待处理；已有产物保留，尚未解决的记录不计为完成。
        </p>
      )}
      {run.status === "failed" && (
        <p className="status-message">
          此次运行失败。请先查看日志与阶段状态，修正后再续跑；未产生的综合结果不会填补。
        </p>
      )}
      <div className="subtabs">
        {(
          [
            { id: "results", name: "产物与结果" },
            { id: "log", name: "运行日志" },
            { id: "manifest", name: "执行清单" },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            className={tab === t.id ? "active" : ""}
            onClick={() => setTab(t.id)}
          >
            {t.name}
          </button>
        ))}
      </div>
      {tab === "log" ? (
        <pre className="log-view" aria-label="实际运行日志">
          {run.log || "日志尚未产生。运行中的日志会自动更新。"}
        </pre>
      ) : tab === "manifest" ? (
        <pre className="json-view">
          {run.manifest ? json(run.manifest) : "执行清单尚未发布。"}
        </pre>
      ) : (
        <>
          <SynthesisSummary run={run} onArtifact={onArtifact} />
          <div className="section-inline">
            <h3>实际产物</h3>
            <span>{run.artifacts.length} 个文件</span>
          </div>
          <ArtifactList artifacts={run.artifacts} onArtifact={onArtifact} />
          {reviewable.length > 0 && (
            <div className="review-actions">
              <div>
                <h3>预测复核</h3>
                <p>修订保留原始预测，并使受影响的下游产物失效。</p>
              </div>
              {reviewable.map((a) => (
                <button
                  className="button small"
                  key={a.key}
                  onClick={() => void onReview(a.key)}
                  disabled={!!busy || active(run.status)}
                >
                  复核{" "}
                  {a.key === "coding_estimates"
                    ? "提取记录"
                    : a.key === "screening_predictions"
                      ? "题摘筛选"
                      : "全文筛选"}
                  <ArrowRight size={14} />
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function ArtifactList({
  artifacts,
  onArtifact,
}: {
  artifacts: Artifact[];
  onArtifact: (artifact: Artifact) => void;
}) {
  if (!artifacts.length)
    return (
      <div className="quiet-empty">
        尚无已发布产物。完成阶段后会显示可检查与下载的文件。
      </div>
    );
  return (
    <div className="artifact-list">
      {artifacts.map((a) => (
        <div className="artifact-row" key={a.key}>
          <FileText size={18} />
          <button className="artifact-name" onClick={() => onArtifact(a)}>
            <strong>{a.name}</strong>
            <small>
              {a.key} ·{" "}
              {a.size < 1024
                ? `${a.size} B`
                : `${(a.size / 1024).toFixed(1)} KB`}
            </small>
          </button>
          <button className="text-button small" onClick={() => onArtifact(a)}>
            检查
          </button>
          <a
            className="icon-button"
            href={a.url + (a.url.includes("?") ? "&" : "?") + "download=1"}
            aria-label={`下载 ${a.name}`}
          >
            <ArrowDownToLine size={16} />
          </a>
        </div>
      ))}
    </div>
  );
}

export function UploadControl({
  upload,
  busy,
}: {
  upload: (file: File) => Promise<void>;
  busy: boolean;
}) {
  return (
    <label className={`button small upload-button ${busy ? "disabled" : ""}`}>
      <Upload size={15} />
      上传文件
      <input
        type="file"
        accept=".pdf,.md,.txt,.jsonl,.csv,.ris"
        disabled={busy}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void upload(file);
          e.target.value = "";
        }}
      />
    </label>
  );
}

export function FilePanel({
  draft,
  artifacts,
  upload,
  onArtifact,
  busy,
}: {
  draft: TaskDetail;
  artifacts: Artifact[];
  upload: (file: File) => Promise<void>;
  onArtifact: (artifact: Artifact) => void;
  busy: boolean;
}) {
  return (
    <div className="file-panel">
      <div className="section-inline">
        <div>
          <h2>文件与证据</h2>
          <p>上传真实文档用于独立编码；产物包含已有的证据、选择和统计结果。</p>
        </div>
        <UploadControl upload={upload} busy={busy} />
      </div>
      {!draft.id && (
        <p className="status-message">请先保存研究方案，再上传文件。</p>
      )}
      <ArtifactList artifacts={artifacts} onArtifact={onArtifact} />
    </div>
  );
}
