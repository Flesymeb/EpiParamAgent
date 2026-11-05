import { useState } from "react";
import { Check, ChevronRight, LoaderCircle, Plus } from "lucide-react";
import { body, request } from "../api";
import type { ReviewPatch } from "../api";
import { json, object } from "../utils";
import { Drawer, ErrorMessage } from "./ui";

export function ReviewDrawer({
  runId,
  initial,
  onClose,
  onSaved,
}: {
  runId: string;
  initial: ReviewPatch;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [patch, setPatch] = useState({ ...initial, reviewer: "", reason: "" });
  const [changes, setChanges] = useState(json(initial.changes));
  const [selected, setSelected] = useState<Record<string, unknown> | null>(
    null,
  );
  const [fields, setFields] = useState("{}");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  function select(row: Record<string, unknown>) {
    setSelected(row);
    if (initial.artifact === "coding_estimates")
      setFields(json({ point_estimate: row.point_estimate ?? null }));
    else {
      const assessments =
        row.criterion_assessments ??
        object(row.protocol_decision).assessments ??
        [];
      setFields(
        json({
          assessments: Array.isArray(assessments)
            ? assessments.map((a) => {
                const x = object(a);
                return {
                  criterion_id: x.criterion_id,
                  status: x.status,
                  evidence: x.evidence,
                  evidence_basis: x.evidence_basis,
                  reason: x.reason,
                };
              })
            : assessments,
        }),
      );
    }
  }
  async function save() {
    setError("");
    setSaving(true);
    try {
      const value = { ...patch, changes: JSON.parse(changes) };
      await request(
        `/runs/${runId}/review`,
        body({ artifact: initial.artifact, patch: value }),
      );
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <Drawer
      title="复核与修订"
      eyebrow="REVISION-BOUND REVIEW"
      onClose={onClose}
    >
      <p className="muted">
        原始预测保持不变。修改需要审核者与理由，版本冲突会保留为错误提示。
      </p>
      <div className="revision">
        修订基线 <code>{initial.revision.slice(0, 16)}</code>
      </div>
      <label>
        审核者
        <input
          value={patch.reviewer}
          onChange={(e) => setPatch({ ...patch, reviewer: e.target.value })}
          placeholder="填写实际审核者身份"
        />
      </label>
      <label className="spaced">
        修订理由
        <textarea
          value={patch.reason}
          onChange={(e) => setPatch({ ...patch, reason: e.target.value })}
          rows={2}
        />
      </label>
      <h3>选择需要检查的记录</h3>
      <div className="review-records">
        {initial.records.map((r, i) => (
          <button
            className={selected === r ? "selected" : ""}
            key={i}
            onClick={() => select(r)}
          >
            <span className="mono">
              {String(r.estimate_id ?? r.record_id ?? i)}
            </span>
            <ChevronRight size={14} />
          </button>
        ))}
      </div>
      {selected && (
        <>
          <details open>
            <summary>原始字段与证据</summary>
            <pre className="json-view">{json(selected)}</pre>
          </details>
          <label>
            本条字段更新 JSON
            <textarea
              className="code-editor"
              rows={7}
              value={fields}
              onChange={(e) => setFields(e.target.value)}
            />
          </label>
          <button
            className="button small"
            onClick={() => {
              try {
                const key =
                  initial.artifact === "coding_estimates"
                    ? "estimate_id"
                    : "record_id";
                const rows = JSON.parse(changes);
                rows.push({ [key]: selected[key], fields: JSON.parse(fields) });
                setChanges(json(rows));
                setError("");
              } catch {
                setError("字段或修订列表 JSON 格式不正确");
              }
            }}
          >
            <Plus size={14} />
            加入修订列表
          </button>
        </>
      )}
      <label className="spaced">
        提交的 changes
        <textarea
          className="code-editor"
          rows={7}
          value={changes}
          onChange={(e) => setChanges(e.target.value)}
        />
      </label>
      {error && <ErrorMessage error={error} />}
      <div className="drawer-footer">
        <button className="button" onClick={onClose}>
          取消
        </button>
        <button
          className="button primary"
          onClick={() => void save()}
          disabled={saving || !patch.reviewer.trim() || !patch.reason.trim()}
        >
          {saving ? (
            <LoaderCircle className="spin" size={15} />
          ) : (
            <Check size={15} />
          )}
          提交修订
        </button>
      </div>
    </Drawer>
  );
}
