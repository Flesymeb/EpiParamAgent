import type { KeyboardEvent } from "react"
import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  ArrowUpRightIcon,
  ClockIcon,
  InboxIcon,
  RefreshCwIcon,
  SearchXIcon,
} from "lucide-react"
import { motion, useReducedMotion } from "motion/react"
import { toast } from "sonner"

import { listRuns } from "@/api/pipeline"
import type { Run } from "@/api/pipeline"
import { QuickStartBox } from "@/components/quick-start-box"
import { BlurText } from "@/components/react-bits/blur-text"
import { SpotlightCard } from "@/components/react-bits/spotlight-card"
import { StatusBadge } from "@/components/status-badge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { getErrorMessage } from "@/lib/errors"
import { normalizeStatus } from "@/lib/status"
import { cn } from "@/lib/utils"

const STATUS_FILTERS = [
  { value: "all", label: "All" },
  { value: "running", label: "Running" },
  { value: "done", label: "Done" },
  { value: "error", label: "Error" },
  { value: "pending", label: "Pending" },
] as const

type StatusFilter = (typeof STATUS_FILTERS)[number]["value"]

type RunsState = {
  runs: Run[]
  error: string | null
  isRefreshing: boolean
  hasLoaded: boolean
}

export function DashboardPage() {
  const navigate = useNavigate()
  const shouldReduceMotion = useReducedMotion()
  const [runsState, setRunsState] = useState<RunsState>({
    runs: [],
    error: null,
    isRefreshing: false,
    hasLoaded: false,
  })

  useEffect(() => {
    let active = true

    async function loadRuns() {
      try {
        const runs = await listRuns()
        if (active) {
          setRunsState({
            runs,
            error: null,
            isRefreshing: false,
            hasLoaded: true,
          })
        }
      } catch (error) {
        const message = getErrorMessage(error)
        if (active) {
          setRunsState({
            runs: [],
            error: message,
            isRefreshing: false,
            hasLoaded: true,
          })
          toast.error(`Failed to load runs: ${message}`)
        }
      }
    }

    void loadRuns()

    return () => {
      active = false
    }
  }, [])

  async function refreshRuns() {
    setRunsState((current) => ({ ...current, isRefreshing: true }))

    try {
      const runs = await listRuns()
      setRunsState({
        runs,
        error: null,
        isRefreshing: false,
        hasLoaded: true,
      })
    } catch (error) {
      const message = getErrorMessage(error)
      setRunsState((current) => ({
        ...current,
        error: message,
        isRefreshing: false,
        hasLoaded: true,
      }))
      toast.error(`Failed to refresh runs: ${message}`)
    }
  }

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all")

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const run of runsState.runs) {
      const status = normalizeStatus(run.status)
      counts[status] = (counts[status] ?? 0) + 1
    }
    return counts
  }, [runsState.runs])

  const visibleRuns = useMemo(
    () =>
      statusFilter === "all"
        ? runsState.runs
        : runsState.runs.filter(
            (run) => normalizeStatus(run.status) === statusFilter
          ),
    [runsState.runs, statusFilter]
  )

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4">
      <QuickStartBox />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-normal">
              <BlurText text="Runs" />
            </h1>
            <Badge variant="outline">
              {runsState.hasLoaded ? `${runsState.runs.length} runs` : "..."}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Pick up a previous review or start a new one above.
          </p>
        </div>
        <Button
          disabled={runsState.isRefreshing}
          onClick={() => {
            void refreshRuns()
          }}
          variant="outline"
        >
          <RefreshCwIcon
            className={cn(
              runsState.isRefreshing &&
                "motion-safe:animate-spin motion-reduce:animate-none"
            )}
          />
          Refresh
        </Button>
      </div>

      {runsState.hasLoaded && runsState.runs.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {STATUS_FILTERS.map((filter) => {
            const count =
              filter.value === "all"
                ? runsState.runs.length
                : statusCounts[filter.value] ?? 0
            const active = statusFilter === filter.value
            return (
              <Button
                className="h-7 gap-1.5 px-2.5 text-xs"
                key={filter.value}
                onClick={() => setStatusFilter(filter.value)}
                size="sm"
                variant={active ? "secondary" : "ghost"}
              >
                {filter.label}
                <span
                  className={cn(
                    "tabular-nums text-muted-foreground",
                    active && "text-foreground/70"
                  )}
                >
                  {count}
                </span>
              </Button>
            )
          })}
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {!runsState.hasLoaded ? (
          RUN_CARD_SKELETON_KEYS.map((key) => <RunCardSkeleton key={key} />)
        ) : runsState.runs.length === 0 ? (
          <Card className="sm:col-span-2 xl:col-span-3 border-dashed bg-muted/20">
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <div className="flex size-12 items-center justify-center rounded-full border bg-background text-muted-foreground">
                <InboxIcon className="size-5" />
              </div>
              <div className="space-y-1">
                <p className="font-medium">
                  {runsState.error ? "Couldn't load runs" : "No runs yet"}
                </p>
                <p className="mx-auto max-w-sm text-sm text-muted-foreground">
                  {runsState.error ??
                    "Describe a systematic-review task in the box above to start your first run."}
                </p>
              </div>
            </CardContent>
          </Card>
        ) : visibleRuns.length === 0 ? (
          <Card className="sm:col-span-2 xl:col-span-3 border-dashed bg-muted/20">
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <div className="flex size-12 items-center justify-center rounded-full border bg-background text-muted-foreground">
                <SearchXIcon className="size-5" />
              </div>
              <div className="space-y-1">
                <p className="font-medium">No {statusFilter} runs</p>
                <p className="mx-auto max-w-sm text-sm text-muted-foreground">
                  No runs match this status filter.{" "}
                  <button
                    className="text-foreground underline-offset-4 hover:underline"
                    onClick={() => setStatusFilter("all")}
                    type="button"
                  >
                    Show all
                  </button>
                </p>
              </div>
            </CardContent>
          </Card>
        ) : (
          visibleRuns.map((run, index) => {
            const facets = runFacets(run)
            const runHref = `/runs/${run.id}`
            const title = runTitle(facets)
            const description =
              facets.researchQuestion && facets.researchQuestion !== title
                ? facets.researchQuestion
                : null

            return (
              <motion.div
                animate={{ opacity: 1, y: 0 }}
                initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
                key={run.id}
                transition={{
                  delay: shouldReduceMotion
                    ? 0
                    : Math.min(index * 0.025, 0.16),
                  duration: shouldReduceMotion ? 0 : 0.22,
                  ease: "easeOut",
                }}
              >
                <SpotlightCard className="flex h-full min-h-44 flex-col rounded-xl border border-border/50 bg-card shadow-sm transition-[transform,box-shadow,border-color] duration-200 will-change-transform hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-xl motion-reduce:transition-none motion-reduce:hover:translate-y-0">
                  <Card
                    className="group flex h-full flex-1 cursor-pointer flex-col gap-0 border-0 bg-transparent shadow-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                    onClick={() => navigate(runHref)}
                    onKeyDown={(event) =>
                      handleRunCardKeyDown(event, () => navigate(runHref))
                    }
                    role="link"
                    tabIndex={0}
                  >
                    <CardHeader className="gap-0 pb-3">
                      <CardTitle
                        className="flex items-start gap-1.5 text-sm font-semibold leading-snug"
                        title={title}
                      >
                        <span className="line-clamp-1">{title}</span>
                        <ArrowUpRightIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                      </CardTitle>
                      <CardAction>
                        <StatusBadge status={run.status} />
                      </CardAction>
                    </CardHeader>
                    <CardContent className="flex flex-1 flex-col gap-3">
                      <div className="flex flex-wrap gap-1.5">
                        {facets.disease ? (
                          <Badge
                            className="border-sky-500/25 bg-sky-500/10 text-sky-700 dark:text-sky-300"
                            variant="outline"
                          >
                            {facets.disease}
                          </Badge>
                        ) : null}
                        {facets.parameter ? (
                          <Badge
                            className="border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300"
                            variant="outline"
                          >
                            {formatParameter(facets.parameter)}
                          </Badge>
                        ) : null}
                        {!facets.disease && !facets.parameter ? (
                          <Badge variant="outline">No params</Badge>
                        ) : null}
                      </div>
                      {description ? (
                        <p
                          className="line-clamp-2 text-xs text-muted-foreground"
                          title={description}
                        >
                          {description}
                        </p>
                      ) : null}
                      <div className="mt-auto flex items-center justify-between gap-2 border-t pt-2.5 text-xs text-muted-foreground">
                        <span
                          className="flex items-center gap-1.5"
                          title={formatDateTime(run.created_at)}
                        >
                          <ClockIcon className="size-3.5" />
                          {formatRelativeTime(run.created_at)}
                        </span>
                        <span
                          className="font-mono text-[0.7rem] text-muted-foreground/70"
                          title={run.id}
                        >
                          {shortRunId(run.id)}
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                </SpotlightCard>
              </motion.div>
            )
          })
        )}
      </div>
    </div>
  )
}

function RunCardSkeleton() {
  return (
    <Card className="min-h-44 gap-0 shadow-sm">
      <CardHeader className="gap-0 pb-3">
        <Skeleton className="h-5 w-40" />
        <CardAction>
          <Skeleton className="h-5 w-20 rounded-4xl" />
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex gap-1.5">
          <Skeleton className="h-5 w-16 rounded-4xl" />
          <Skeleton className="h-5 w-24 rounded-4xl" />
        </div>
        <Skeleton className="h-4 w-full" />
        <div className="flex items-center justify-between border-t pt-2.5">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-16" />
        </div>
      </CardContent>
    </Card>
  )
}

function handleRunCardKeyDown(
  event: KeyboardEvent<HTMLDivElement>,
  openRun: () => void
) {
  if (event.key !== "Enter" && event.key !== " ") {
    return
  }

  event.preventDefault()
  openRun()
}

function shortRunId(runId: string) {
  return runId.length > 12 ? `${runId.slice(0, 8)}...` : runId
}

function formatDateTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return date.toLocaleString([], {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function formatRelativeTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  const diffMs = Date.now() - date.getTime()
  const isFuture = diffMs < 0
  const absoluteDiffMs = Math.abs(diffMs)
  const minuteMs = 60 * 1000
  const hourMs = 60 * minuteMs
  const dayMs = 24 * hourMs

  if (absoluteDiffMs < minuteMs) {
    return isFuture ? "in a moment" : "just now"
  }

  if (absoluteDiffMs < hourMs) {
    const minutes = Math.round(absoluteDiffMs / minuteMs)
    return isFuture ? `in ${minutes}m` : `${minutes}m ago`
  }

  if (absoluteDiffMs < dayMs) {
    const hours = Math.round(absoluteDiffMs / hourMs)
    return isFuture ? `in ${hours}h` : `${hours}h ago`
  }

  const days = Math.round(absoluteDiffMs / dayMs)
  return isFuture ? `in ${days}d` : `${days}d ago`
}

function runFacets(run: Run) {
  return {
    disease: stringifyParam(run.params.disease),
    parameter: stringifyParam(run.params.parameter),
    keywords: stringifyParam(run.params.keywords),
    researchQuestion: stringifyParam(run.params.research_question),
  }
}

// A readable card title derived from run params, falling back gracefully so the
// card never shows a raw run id as its name.
function runTitle(facets: ReturnType<typeof runFacets>): string {
  if (facets.keywords) {
    return facets.keywords
  }
  if (facets.disease || facets.parameter) {
    return [
      facets.disease,
      facets.parameter ? formatParameter(facets.parameter) : null,
    ]
      .filter(Boolean)
      .join(" · ")
  }
  return "Untitled run"
}

function formatParameter(value: string) {
  return value.replaceAll("_", " ")
}

function stringifyParam(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null
}

const RUN_CARD_SKELETON_KEYS = [
  "run-1",
  "run-2",
  "run-3",
  "run-4",
  "run-5",
  "run-6",
]
