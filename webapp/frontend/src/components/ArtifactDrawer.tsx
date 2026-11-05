import { useEffect, useState } from "react";
import { ArrowDownToLine, LoaderCircle } from "lucide-react";
import type { Artifact } from "../api";
import { json, object } from "../utils";
import { artifactPreviewKind } from "../artifact-preview";
import { Drawer, ErrorMessage } from "./ui";

export function ArtifactDrawer({
  artifact,
  onClose,
}: {
  artifact: Artifact;
  onClose: () => void;
}) {
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const previewKind = artifactPreviewKind(artifact);
  const previewUrl =
    artifact.url + (artifact.url.includes("?") ? "&" : "?") + "download=false";
  useEffect(() => {
    if (previewKind !== "text") return;
    let live = true;
    void fetch(previewUrl)
      .then((r) => {
        if (!r.ok) throw new Error(`文件读取失败：${r.status}`);
        return r.text();
      })
      .then((text) => {
        if (live) setContent(text);
      })
      .catch((e) => {
        if (live) setError(e.message);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [artifact, previewUrl, previewKind]);
  let records: Record<string, unknown>[] = [];
  try {
    if (artifact.name.endsWith(".jsonl"))
      records = content
        .split("\n")
        .filter(Boolean)
        .map((line) => object(JSON.parse(line)));
    else if (artifact.name.endsWith(".json")) {
      const value = JSON.parse(content);
      if (Array.isArray(value)) records = value.map(object);
      else if (value.result) records = [object(value.result)];
      else records = [object(value)];
    }
  } catch {
    /* Preserve raw content for inspection. */
  }
  const columns = records.length
    ? Object.keys(records[0])
        .filter(
          (k) => !["source_raw", "raw_values", "evidence_json"].includes(k),
        )
        .slice(0, 8)
    : [];
  return (
    <Drawer
      title={artifact.name}
      eyebrow="ARTIFACT INSPECTOR"
      onClose={onClose}
    >
      <a
        className="button small"
        href={
          artifact.url + (artifact.url.includes("?") ? "&" : "?") + "download=1"
        }
      >
        <ArrowDownToLine size={15} />
        下载原始文件
      </a>
      {previewKind === "image" ? (
        <img className="artifact-image" src={previewUrl} alt={artifact.name} />
      ) : previewKind === "pdf" ? (
        <iframe
          className="pdf-preview"
          title={artifact.name}
          src={previewUrl}
        />
      ) : previewKind === "download" ? (
        <p className="quiet-empty">
          此类型请下载查看。为避免二进制乱码，不进行文本预览。
        </p>
      ) : (
        <>
          {loading ? (
            <div className="loading">
              <LoaderCircle className="spin" size={17} />
              读取实际产物…
            </div>
          ) : error ? (
            <ErrorMessage error={error} />
          ) : (
            <>
              {records.length > 0 && (
                <div className="table-wrap result-table">
                  <table>
                    <thead>
                      <tr>
                        {columns.map((k) => (
                          <th key={k}>{k}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {records.slice(0, 100).map((row, i) => (
                        <tr key={i}>
                          {columns.map((k) => (
                            <td key={k}>
                              {typeof row[k] === "object"
                                ? json(row[k])
                                : String(row[k] ?? "—")}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {records.length > 100 && (
                    <p className="field-hint">
                      预览前 100 条；下载包含全部记录。
                    </p>
                  )}
                </div>
              )}
              <details className="raw-details">
                <summary>查看原始内容与证据字段</summary>
                <pre className="json-view">{content || "文件为空"}</pre>
              </details>
            </>
          )}
        </>
      )}
    </Drawer>
  );
}
