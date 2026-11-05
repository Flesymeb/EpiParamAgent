import { useState } from "react";
import { dump, load } from "js-yaml";
import { Check, ChevronDown, ChevronRight } from "lucide-react";
import type { TaskDetail, Mode } from "../api";
import { modeLabels } from "../api";
import { json, object } from "../utils";
import { readAnalysisProtocol, writeAnalysisProtocol } from "../task-protocol";
import { ErrorMessage } from "./ui";
import { UploadControl } from "./RunWorkspace";
const sources = [
  "pubmed",
  "europepmc",
  "medrxiv",
  "biorxiv",
  "openalex",
  "crossref",
];
const sourceNames: Record<string, string> = {
  pubmed: "PubMed",
  europepmc: "Europe PMC",
  medrxiv: "medRxiv",
  biorxiv: "bioRxiv",
  openalex: "OpenAlex",
  crossref: "Crossref",
};

export function TaskEditor({
  draft,
  onEdit,
  onInvalid,
  mode,
  setMode,
  input,
  setInput,
  limit,
  setLimit,
  upload,
  busy,
}: {
  draft: TaskDetail;
  onEdit: (changes: Partial<TaskDetail>) => void;
  onInvalid: (field: string, invalid: boolean) => void;
  mode: Mode;
  setMode: (mode: Mode) => void;
  input: string;
  setInput: (input: string) => void;
  limit: string;
  setLimit: (limit: string) => void;
  upload: (file: File) => Promise<void>;
  busy: boolean;
}) {
  const [advanced, setAdvanced] = useState(false);
  const [localError, setLocalError] = useState("");
  let doc: Record<string, unknown> = {};
  try {
    doc = object(load(draft.task_yaml));
  } catch {
    /* Invalid YAML stays editable in advanced mode. */
  }
  function update(path: string[], value: unknown) {
    try {
      const next = object(load(draft.task_yaml));
      let target = next;
      for (const key of path.slice(0, -1)) {
        target[key] = object(target[key]);
        target = object(target[key]);
      }
      target[path.at(-1)!] = value;
      onEdit({ task_yaml: dump(next, { lineWidth: 110, noRefs: true }) });
      setLocalError("");
    } catch (e) {
      setLocalError(
        `请先修正完整 YAML：${e instanceof Error ? e.message : String(e)}`,
      );
      setAdvanced(true);
    }
  }
  const protocol = object(doc.review_protocol);
  const search = object(doc.search);
  return (
    <div className="editor">
      <section>
        <div className="section-heading">
          <span className="section-number">01</span>
          <div>
            <h2>研究问题</h2>
            <p>问题与协议共同定义检索和文献资格。</p>
          </div>
        </div>
        <div className="fields">
          <label>
            任务名称
            <input
              value={draft.name}
              onChange={(e) => onEdit({ name: e.target.value })}
              placeholder="为本次研究命名"
            />
          </label>
          <label>
            研究问题
            <textarea
              rows={3}
              value={String(doc.research_question ?? "")}
              onChange={(e) => update(["research_question"], e.target.value)}
              placeholder="需要从文献中回答什么问题？"
            />
          </label>
          <div className="field-row">
            <label>
              病种 / 研究领域
              <input
                value={String(doc.disease ?? "")}
                onChange={(e) => update(["disease"], e.target.value)}
              />
            </label>
            <label>
              参数主题
              <input
                value={String(doc.topic ?? "")}
                onChange={(e) => update(["topic"], e.target.value)}
              />
            </label>
          </div>
        </div>
      </section>
      <section>
        <div className="section-heading">
          <span className="section-number">02</span>
          <div>
            <h2>纳排与分析协议</h2>
            <p>筛选按完整综述范围；具体估计的选择在综合阶段执行。</p>
          </div>
        </div>
        <label>
          Review protocol
          <span className="field-hint">
            JSON 编辑保留所有标准、条件与 AND / OR 逻辑
          </span>
          <JsonEditor
            onInvalid={(invalid) => onInvalid("review", invalid)}
            value={protocol}
            onSave={(v) => update(["review_protocol"], v)}
          />
        </label>
        <label className="spaced">
          Analysis protocol
          <span className="field-hint">
            支持独立 analysis_protocol 或多分析 analysis_protocols
          </span>
          <JsonEditor
            onInvalid={(invalid) => onInvalid("analysis", invalid)}
            value={readAnalysisProtocol(doc)}
            onSave={(v) => {
              const next = writeAnalysisProtocol(
                object(load(draft.task_yaml)),
                v,
              );
              onEdit({
                task_yaml: dump(next, { lineWidth: 110, noRefs: true }),
              });
            }}
          />
        </label>
      </section>
      <section>
        <div className="section-heading">
          <span className="section-number">03</span>
          <div>
            <h2>检索来源</h2>
            <p>
              每个启用的来源使用自己的查询式。medRxiv / bioRxiv 通过 Europe PMC
              发现。
            </p>
          </div>
        </div>
        <div className="source-list">
          {sources.map((s) => (
            <div className="source-row" key={s}>
              <label>{sourceNames[s]}</label>
              <textarea
                rows={2}
                aria-label={`${sourceNames[s]} 查询式`}
                placeholder="留空表示不执行此来源"
                value={String(search[s] ?? "")}
                onChange={(e) => {
                  const next = { ...search };
                  if (e.target.value.trim()) next[s] = e.target.value;
                  else delete next[s];
                  update(["search"], next);
                }}
              />
            </div>
          ))}
        </div>
      </section>
      <section>
        <div className="section-heading">
          <span className="section-number">04</span>
          <div>
            <h2>编码与完整配置</h2>
            <p>
              A 提取候选，B 核查定稿。高级 YAML 保留未在表单中显示的所有设置。
            </p>
          </div>
        </div>
        <label>
          Codebook YAML
          <textarea
            className="code-editor"
            spellCheck={false}
            rows={12}
            value={draft.codebook_yaml}
            onChange={(e) => onEdit({ codebook_yaml: e.target.value })}
          />
        </label>
        <button
          className="text-button"
          onClick={() => setAdvanced(!advanced)}
          aria-expanded={advanced}
        >
          {advanced ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          完整任务 YAML · 包含模型与高级字段
        </button>
        {advanced && (
          <textarea
            aria-label="完整任务 YAML"
            className="code-editor"
            spellCheck={false}
            rows={18}
            value={draft.task_yaml}
            onChange={(e) => onEdit({ task_yaml: e.target.value })}
          />
        )}
        {localError && <ErrorMessage error={localError} />}
      </section>
      <section>
        <div className="section-heading">
          <span className="section-number">05</span>
          <div>
            <h2>运行范围</h2>
            <p>默认完整流程；三个模块也可读取自己的输入单独执行。</p>
          </div>
        </div>
        <div className="field-row">
          <label>
            执行模式
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as Mode)}
            >
              {Object.entries(modeLabels).map(([key, label]) => (
                <option value={key} key={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            每来源记录上限
            <input
              type="number"
              min="1"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              placeholder="不限制（完整分页）"
            />
          </label>
        </div>
        <div className="flow-note">
          <Check size={16} />
          Coding 默认 full · A 候选提取＋B 语义定稿
        </div>
        {mode !== "end_to_end" && (
          <>
            <div className="input-heading">
              <label>模块输入 JSONL</label>
              <UploadControl upload={upload} busy={busy} />
            </div>
            <p className="field-hint">
              {mode === "screening"
                ? "每行一条题录，包含 record_id、title、abstract 等。"
                : mode === "coding"
                  ? "每行一个文档，包含 record_id、path；上传 PDF / Markdown 后会填入托管路径。"
                  : "每行一条结构化估计，字段与分析协议一致；请保留 estimate_id、队列身份与证据。"}
            </p>
            <textarea
              className="code-editor"
              aria-label="模块输入 JSONL"
              rows={8}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                mode === "coding"
                  ? "上传文档以生成真实文件路径"
                  : "粘贴 JSONL 输入；不会填充虚构研究数据"
              }
            />
          </>
        )}
      </section>
    </div>
  );
}

function JsonEditor({
  value,
  onSave,
  onInvalid,
}: {
  value: unknown;
  onSave: (value: unknown) => void;
  onInvalid: (invalid: boolean) => void;
}) {
  const rendered = json(value);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState("");
  return (
    <>
      <textarea
        className="code-editor compact"
        rows={8}
        spellCheck={false}
        value={editing ?? rendered}
        onChange={(e) => {
          const text = e.target.value;
          setEditing(text);
          try {
            const parsed = JSON.parse(text);
            onSave(parsed);
            onInvalid(false);
            setError("");
          } catch {
            onInvalid(true);
            setError("JSON 格式有误，请修正后再保存方案。");
          }
        }}
        onBlur={() => {
          if (!error) setEditing(null);
        }}
      />
      {error && <ErrorMessage error={error} />}
    </>
  );
}
