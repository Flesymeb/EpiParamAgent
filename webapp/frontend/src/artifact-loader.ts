/** Artifact URLs are stable across resume; their content revision is not. */
export function synthesisRevision(run: {
  id: string;
  status: string;
  updated_at: string;
  stage_results: Record<string, unknown>;
  manifest: Record<string, unknown> | null;
}): string {
  const asObject = (value: unknown): Record<string, unknown> =>
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  const manifest = asObject(run.manifest);
  const pooling = {
    ...asObject(asObject(manifest.stage_results).pooling),
    ...asObject(run.stage_results.pooling),
  };
  const artifact = asObject(manifest.artifacts).synthesis_result;
  const path =
    typeof artifact === "string" ? artifact : asObject(artifact).path;
  const contentHash =
    typeof path === "string"
      ? asObject(pooling.output_hashes)[path]
      : undefined;
  return JSON.stringify([
    run.id,
    run.status,
    run.updated_at,
    pooling.fingerprint ?? null,
    contentHash ?? null,
    pooling.stale ?? false,
  ]);
}

/** Abort plus publish guard also protects against transports that resolve after abort. */
export function loadJsonArtifact(
  url: string,
  revision: string,
  onValue: (value: unknown) => void,
  onError: (error: Error) => void,
  transport: typeof fetch = fetch,
): () => void {
  const controller = new AbortController();
  let cancelled = false;
  const target =
    url +
    (url.includes("?") ? "&" : "?") +
    "revision=" +
    encodeURIComponent(revision);
  void transport(target, { cache: "no-store", signal: controller.signal })
    .then(async (response) => {
      if (!response.ok) throw new Error(`综合产物读取失败：${response.status}`);
      return response.json();
    })
    .then((value) => {
      if (!cancelled) onValue(value);
    })
    .catch((error) => {
      if (!cancelled)
        onError(error instanceof Error ? error : new Error(String(error)));
    });
  return () => {
    cancelled = true;
    controller.abort();
  };
}
