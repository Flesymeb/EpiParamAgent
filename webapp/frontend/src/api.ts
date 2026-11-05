export type ModuleName = "query" | "screening" | "coding" | "synthesis";
export type Mode = "end_to_end" | "screening" | "coding" | "synthesis";
export type Runtime = {
  provider: string;
  model: string;
  api_base: string;
  thinking?: string | null;
  timeout_s: number;
  max_tokens: number;
  api_key_configured: boolean;
  api_key?: string;
  provider_changed?: boolean;
};
export type RunSummary = {
  id: string;
  task_id: string;
  name: string;
  mode: Mode;
  status: string;
  created_at: string;
  updated_at: string;
  stage_results: Record<string, unknown>;
  error?: string | null;
};
export type Artifact = {
  key: string;
  name: string;
  size: number;
  media_type: string;
  url: string;
};
export type RunDetail = RunSummary & {
  manifest: Record<string, unknown> | null;
  artifacts: Artifact[];
  log: string;
};
export type TaskSummary = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  latest_run?: RunSummary | null;
};
export type TaskDetail = TaskSummary & {
  task_yaml: string;
  codebook_yaml: string;
};
export type Config = {
  modules: Record<ModuleName, Runtime>;
  mineru: Record<string, unknown>;
  sources: Record<string, unknown>;
};
export type ReviewPatch = {
  artifact: string;
  revision: string;
  records: Record<string, unknown>[];
  reviewer: string;
  reason: string;
  changes: unknown[];
};

export async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch("/api" + path, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail =
      payload?.detail ?? `${response.status} ${response.statusText}`;
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  return response.json() as Promise<T>;
}
export function body(value: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  };
}
export function labelStatus(status?: string) {
  const labels: Record<string, string> = {
    queued: "排队中",
    running: "运行中",
    complete: "完成",
    completed: "完成",
    partial: "部分完成",
    failed: "失败",
    interrupted: "已中断",
    not_started: "未开始",
    pending: "待核实",
    single_estimate: "单估计结果",
    not_computable: "无法综合",
    protocol_pending: "协议待完善",
    ready: "就绪",
  };
  return status ? (labels[status] ?? status) : "尚未运行";
}
export const modeLabels: Record<Mode, string> = {
  end_to_end: "完整端到端",
  screening: "独立筛选",
  coding: "独立编码",
  synthesis: "独立综合",
};
export const moduleLabels: Record<ModuleName, string> = {
  query: "查询生成",
  screening: "文献筛选",
  coding: "候选提取与定稿",
  synthesis: "统计综合与报告",
};
