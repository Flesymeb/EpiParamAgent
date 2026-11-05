import { useEffect, useState } from "react";
import { FileText, LoaderCircle } from "lucide-react";
import type { Artifact, RunDetail } from "../api";
import { object } from "../utils";
import { loadJsonArtifact, synthesisRevision } from "../artifact-loader";
import { synthesisAnalyses, synthesisReviewReasons } from "../synthesis-view";
import { ErrorMessage, Status } from "./ui";

function number(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("zh-CN", { maximumSignificantDigits: 7 }).format(
        value,
      )
    : "未提供";
}

export function SynthesisSummary({
  run,
  onArtifact,
}: {
  run: RunDetail;
  onArtifact: (artifact: Artifact) => void;
}) {
  const source = run.artifacts.find((a) => a.key === "synthesis_result");
  if (!source)
    return (
      <div className="quiet-empty">
        尚未发布综合结果。请查看实际阶段状态与日志。
      </div>
    );
  const revision = synthesisRevision(run);
  const stale =
    object(object(run.stage_results).pooling).stale === true ||
    object(object(run.manifest?.stage_results).pooling).stale === true;
  return (
    <LoadedSummary
      key={`${source.url}:${revision}`}
      source={source}
      revision={revision}
      artifacts={run.artifacts}
      stale={stale}
      onArtifact={onArtifact}
    />
  );
}

function LoadedSummary({
  source,
  revision,
  artifacts,
  stale,
  onArtifact,
}: {
  source: Artifact;
  revision: string;
  artifacts: Artifact[];
  stale: boolean;
  onArtifact: (artifact: Artifact) => void;
}) {
  const [document, setDocument] = useState<unknown>(null);
  const [error, setError] = useState("");
  useEffect(
    () =>
      loadJsonArtifact(source.url, revision, setDocument, (error) =>
        setError(error.message),
      ),
    [source.url, revision],
  );
  if (error) return <ErrorMessage error={error} />;
  if (!document)
    return (
      <div className="loading">
        <LoaderCircle size={17} className="spin" />
        读取实际综合结果…
      </div>
    );
  const analyses = synthesisAnalyses(document);
  const multiple = Array.isArray(object(document).analyses);
  return (
    <section className="synthesis-summary">
      <div className="section-inline">
        <h3>综合结果</h3>
        {multiple && (
          <Status
            value={
              typeof object(document).status === "string"
                ? String(object(document).status)
                : undefined
            }
          />
        )}
        <button
          className="text-button small"
          onClick={() => onArtifact(source)}
        >
          <FileText size={13} />
          原始计算产物
        </button>
      </div>
      {stale && (
        <p className="status-message">
          上游已经修订，以下为已过期的历史综合产物；续跑完成前不能视为当前结果。
        </p>
      )}
      {!analyses.length && (
        <p className="quiet-empty">
          此产物没有可识别的分析记录，请检查原始文件。
        </p>
      )}
      {analyses.map((analysis, index) => {
        const result = object(analysis.result);
        const counts = object(analysis.counts);
        const reasons = synthesisReviewReasons(analysis);
        const exists =
          typeof result.pooled_mean === "number" &&
          Number.isFinite(result.pooled_mean);
        const interval =
          typeof result.ci_lower === "number" &&
          typeof result.ci_upper === "number" &&
          Number.isFinite(result.ci_lower) &&
          Number.isFinite(result.ci_upper);
        const forestKey = multiple
          ? `analysis_${String(index + 1).padStart(3, "0")}/forest_png`
          : "forest_png";
        const forest = artifacts.find((a) => a.key === forestKey);
        return (
          <article
            className="analysis-summary"
            key={String(analysis.analysis_id ?? index)}
          >
            <div className="analysis-title">
              <h3>{String(analysis.analysis_id ?? "未提供分析 ID")}</h3>
              <Status
                value={
                  typeof analysis.status === "string"
                    ? analysis.status
                    : undefined
                }
              />
            </div>
            {exists ? (
              <>
                <div className="synthesis-estimate">
                  <strong title={String(result.pooled_mean)}>
                    {number(result.pooled_mean)}
                  </strong>
                  <span>
                    {typeof result.unit === "string"
                      ? result.unit
                      : "单位未提供"}
                  </span>
                </div>
                <dl className="synthesis-details">
                  <div>
                    <dt>统计方法</dt>
                    <dd>
                      {String(
                        result.method_detail ?? result.method ?? "未提供",
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>区间</dt>
                    <dd>
                      {interval
                        ? `${typeof result.ci_level === "number" ? number(result.ci_level * 100) + "% " : ""}${typeof result.ci_type === "string" ? result.ci_type + " " : ""}[${number(result.ci_lower)}, ${number(result.ci_upper)}]`
                        : "未生成区间"}
                      {Boolean(result.interval_status) && (
                        <small>{String(result.interval_status)}</small>
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>纳入估计</dt>
                    <dd>{number(counts.selected ?? result.n_estimates)}</dd>
                  </div>
                  <div>
                    <dt>独立单元</dt>
                    <dd>
                      {number(
                        counts.independent_units ?? result.n_independent_units,
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>待审记录</dt>
                    <dd>{number(counts.review)}</dd>
                  </div>
                </dl>
              </>
            ) : (
              <div>
                <p className="status-message">
                  无可用综合数值。此状态不表示没有效应；请检查协议、输入与待审原因。
                </p>
                <p className="field-hint">
                  纳入估计：{number(counts.selected)} · 待审记录：
                  {number(counts.review)}
                </p>
              </div>
            )}
            {reasons.length > 0 && (
              <details className="summary-reasons" open={!exists}>
                <summary>待审 / 未综合原因（{reasons.length}）</summary>
                <ul>
                  {reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </details>
            )}
            {forest && exists && (
              <details className="summary-forest">
                <summary>森林图 · 实际统计产物</summary>
                <a
                  href={
                    forest.url +
                    (forest.url.includes("?") ? "&" : "?") +
                    "download=false&revision=" +
                    encodeURIComponent(revision)
                  }
                  target="_blank"
                  rel="noreferrer"
                >
                  <img
                    src={
                      forest.url +
                      (forest.url.includes("?") ? "&" : "?") +
                      "download=false&revision=" +
                      encodeURIComponent(revision)
                    }
                    alt={`${String(analysis.analysis_id ?? "分析")} 的实际森林图`}
                  />
                </a>
              </details>
            )}
          </article>
        );
      })}
    </section>
  );
}
