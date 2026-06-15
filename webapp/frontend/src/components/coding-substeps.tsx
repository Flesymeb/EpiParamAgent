import { CheckIcon, DownloadIcon, ListChecksIcon, TableIcon, XIcon } from "lucide-react"
import type { LucideIcon } from "lucide-react"

import type { RunEvent } from "@/api/pipeline"
import type { NormalizedStatus } from "@/lib/status"
import { cn } from "@/lib/utils"

type SubStageId = "fetch" | "index" | "extract"

type SubStage = {
  id: SubStageId
  label: string
  icon: LucideIcon
}

const SUBSTAGES: SubStage[] = [
  { id: "fetch", label: "Fetch PDFs", icon: DownloadIcon },
  { id: "index", label: "Index", icon: ListChecksIcon },
  { id: "extract", label: "Extract", icon: TableIcon },
]

// Which sub-stages the chosen `stage` actually exercises. Fetch is implicit
// (run_pipeline fetches missing PDFs on demand) so it shows for most stages.
function inScopeFor(stage: string): SubStageId[] {
  switch (stage) {
    case "fetch":
      return ["fetch"]
    case "index":
      return ["fetch", "index"]
    case "both":
    case "extract":
    default:
      // "extract" and "both" both fetch missing PDFs on demand, then index,
      // then extract — show the full chain.
      return ["fetch", "index", "extract"]
  }
}

// Best-effort detection of the running sub-stage from the latest log line.
// Skips the setup echo (`coding step: stage=…`) so it isn't mistaken for the
// extract stage starting.
function detectCurrent(events: RunEvent[]): SubStageId | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const message = events[i].message.toLowerCase()
    if (message.includes("coding step:")) {
      continue
    }
    if (
      message.includes("coding_sheet") ||
      message.includes("manifest") ||
      message.includes("[extract")
    ) {
      return "extract"
    }
    if (message.includes("[index]")) {
      return "index"
    }
    if (
      message.includes("mineru") ||
      message.includes("[md") ||
      message.includes(".pdf")
    ) {
      return "fetch"
    }
  }
  return null
}

type SubStageState = "finish" | "process" | "error" | "wait"

export function CodingSubsteps({
  stage,
  status,
  events,
}: {
  stage: string
  status: NormalizedStatus
  events: RunEvent[]
}) {
  const scope = inScopeFor(stage)
  const current = detectCurrent(events)
  const currentIndex = current ? scope.indexOf(current) : -1

  // While running, the current sub-stage is the one in progress; on error, the
  // furthest-reached sub-stage is where it failed.
  const runningIndex = currentIndex >= 0 ? currentIndex : 0
  const errorIndex = currentIndex >= 0 ? currentIndex : scope.length - 1

  function stateFor(index: number): SubStageState {
    if (status === "done") return "finish"
    if (status === "error") {
      if (index < errorIndex) return "finish"
      if (index === errorIndex) return "error"
      return "wait"
    }
    if (status === "running") {
      if (index < runningIndex) return "finish"
      if (index === runningIndex) return "process"
      return "wait"
    }
    return "wait"
  }

  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="mr-1 text-xs font-medium text-muted-foreground">
        Stages
      </span>
      {SUBSTAGES.map((sub) => {
        const scopeIndex = scope.indexOf(sub.id)
        const skipped = scopeIndex === -1
        const subState: SubStageState | "skip" = skipped
          ? "skip"
          : stateFor(scopeIndex)
        return (
          <div className="flex items-center gap-1" key={sub.id}>
            <SubStageDot icon={sub.icon} state={subState} />
            <span
              className={cn(
                "text-xs",
                subState === "skip"
                  ? "text-muted-foreground/50"
                  : subState === "process"
                    ? "font-medium text-sky-700 dark:text-sky-300"
                    : subState === "finish"
                      ? "text-emerald-700 dark:text-emerald-300"
                      : subState === "error"
                        ? "text-destructive"
                        : "text-muted-foreground"
              )}
            >
              {sub.label}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function SubStageDot({
  icon: Icon,
  state,
}: {
  icon: LucideIcon
  state: SubStageState | "skip"
}) {
  return (
    <span
      className={cn(
        "relative flex size-5 items-center justify-center rounded-full border text-[0.6rem]",
        state === "finish" &&
          "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
        state === "process" &&
          "border-sky-500/40 bg-sky-500/10 text-sky-600 dark:text-sky-300",
        state === "error" && "border-destructive/40 bg-destructive/10 text-destructive",
        (state === "wait" || state === "skip") &&
          "border-border bg-background text-muted-foreground",
        state === "skip" && "opacity-50"
      )}
    >
      {state === "process" ? (
        <span
          aria-hidden="true"
          className="absolute -inset-0.5 rounded-full border-2 border-sky-500/70 border-t-transparent motion-safe:animate-spin motion-reduce:animate-none"
        />
      ) : null}
      {state === "finish" ? (
        <CheckIcon className="size-3" />
      ) : state === "error" ? (
        <XIcon className="size-3" />
      ) : (
        <Icon className="size-3" />
      )}
    </span>
  )
}
