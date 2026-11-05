export function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
export function json(value: unknown) {
  return JSON.stringify(value, null, 2);
}
export function time(value?: string) {
  return value
    ? new Date(value).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
}
export const active = (status?: string) =>
  status === "running" || status === "queued";
export const stages = [
  { key: "retrieval", name: "检索", sub: "Query / Retrieval" },
  { key: "screening", name: "题摘筛选", sub: "Screening" },
  { key: "fulltext_fetch", name: "全文获取", sub: "Document cache" },
  { key: "fulltext_screening", name: "全文筛选", sub: "Eligibility" },
  { key: "coding", name: "编码", sub: "A 候选 → B 定稿" },
  { key: "pooling", name: "综合", sub: "Synthesis" },
];
