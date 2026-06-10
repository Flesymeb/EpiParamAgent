export type NormalizedStatus = "pending" | "running" | "done" | "error"

export function normalizeStatus(status: string | null | undefined): NormalizedStatus {
  const value = status?.toLowerCase() ?? "pending"

  if (["done", "complete", "completed", "success", "succeeded"].includes(value)) {
    return "done"
  }

  if (["running", "started", "in_progress", "queued"].includes(value)) {
    return "running"
  }

  if (["error", "failed", "failure"].includes(value)) {
    return "error"
  }

  return "pending"
}

export function getStatusLabel(status: string | null | undefined): string {
  return normalizeStatus(status)
}

export function getStatusClassName(status: string | null | undefined): string {
  switch (normalizeStatus(status)) {
    case "done":
      return "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
    case "running":
      return "border-blue-500/25 bg-blue-500/10 text-blue-700 dark:text-blue-300"
    case "error":
      return "border-destructive/30 bg-destructive/10 text-destructive"
    case "pending":
      return "border-border bg-muted text-muted-foreground"
  }
}
