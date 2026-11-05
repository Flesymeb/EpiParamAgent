/** Preview only declared text formats; binary artifacts remain download-only. */
export function artifactPreviewKind(artifact: {
  name: string;
  media_type?: string;
}): "image" | "pdf" | "text" | "download" {
  const mime = (artifact.media_type ?? "").split(";")[0].trim().toLowerCase();
  if (
    mime.startsWith("image/") ||
    /\.(png|jpe?g|webp|gif|svg)$/i.test(artifact.name)
  )
    return "image";
  if (mime === "application/pdf" || /\.pdf$/i.test(artifact.name)) return "pdf";
  // An explicit binary extension wins over an inaccurate generic text MIME.
  if (
    /\.(xlsx?|zip|gz|bz2|xz|tar|7z|parquet|arrow|sqlite3?|db|docx?|pptx?|bin)$/i.test(
      artifact.name,
    )
  )
    return "download";
  if (
    /\.(txt|json|jsonl|ndjson|md|markdown|csv|tsv|ya?ml|xml|log|ris)$/i.test(
      artifact.name,
    )
  )
    return "text";
  if (
    mime.startsWith("text/") ||
    [
      "application/json",
      "application/ndjson",
      "application/x-ndjson",
      "application/yaml",
      "application/x-yaml",
      "application/xml",
    ].includes(mime) ||
    mime.endsWith("+json") ||
    mime.endsWith("+xml")
  )
    return "text";
  return "download";
}
