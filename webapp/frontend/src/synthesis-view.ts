/** Interpret authoritative synthesis artifacts without inferring absent values. */
export function synthesisAnalyses(value: unknown): Record<string, unknown>[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const root = value as Record<string, unknown>;
  const candidates = Array.isArray(root.analyses) ? root.analyses : [root];
  return candidates.filter(
    (item): item is Record<string, unknown> =>
      !!item && typeof item === "object" && !Array.isArray(item),
  );
}

export function synthesisReviewReasons(
  analysis: Record<string, unknown>,
): string[] {
  const reasons: string[] = [];
  if (typeof analysis.reason === "string") reasons.push(analysis.reason);
  if (Array.isArray(analysis.protocol_gaps))
    reasons.push(
      ...analysis.protocol_gaps.filter(
        (value): value is string => typeof value === "string",
      ),
    );
  if (Array.isArray(analysis.selection)) {
    for (const entry of analysis.selection) {
      if (!entry || typeof entry !== "object" || entry.decision !== "review")
        continue;
      const issues = Array.isArray(entry.reasons)
        ? entry.reasons
            .filter((value: unknown) => typeof value === "string")
            .join("; ")
        : "";
      if (issues)
        reasons.push(
          `${String(entry.estimate_id ?? "未提供估计 ID")}：${issues}`,
        );
    }
  }
  return [...new Set(reasons)];
}
