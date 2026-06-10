import type { FormEvent, KeyboardEvent } from "react"
import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { LoaderCircleIcon, PlayIcon, RefreshCwIcon } from "lucide-react"
import { motion, useReducedMotion } from "motion/react"
import { toast } from "sonner"

import { createRun, listRuns } from "@/api/pipeline"
import type { Run } from "@/api/pipeline"
import Aurora from "@/components/Aurora"
import { StatusBadge } from "@/components/status-badge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { API_BASE_URL } from "@/lib/config"
import { getErrorMessage } from "@/lib/errors"
import { cn } from "@/lib/utils"

const diseaseOptions = ["mpox", "covid19"] as const
const parameterOptions = [
  "serial_interval",
  "reproduction_number",
  "fatality",
] as const

type RunFormState = {
  keywords: string
  research_question: string
  disease: (typeof diseaseOptions)[number]
  parameter: (typeof parameterOptions)[number]
}

type RunsState = {
  runs: Run[]
  error: string | null
  isRefreshing: boolean
  hasLoaded: boolean
}

const initialForm: RunFormState = {
  keywords: "",
  research_question: "",
  disease: "mpox",
  parameter: "serial_interval",
}

const selectClassName =
  "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 py-1 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30"

const headerAuroraStops = ["#38bdf8", "#64748b", "#f59e0b"]

export function DashboardPage() {
  const navigate = useNavigate()
  const shouldReduceMotion = useReducedMotion()
  const [form, setForm] = useState<RunFormState>(initialForm)
  const [isCreating, setIsCreating] = useState(false)
  const [runsState, setRunsState] = useState<RunsState>({
    runs: [],
    error: null,
    isRefreshing: false,
    hasLoaded: false,
  })
  const canCreate = form.keywords.trim().length > 0 && !isCreating

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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!form.keywords.trim()) {
      return
    }
    setIsCreating(true)

    try {
      const run = await createRun({
        keywords: form.keywords.trim(),
        research_question: form.research_question.trim(),
        disease: form.disease,
        parameter: form.parameter,
      })
      navigate(`/runs/${run.id}`)
    } catch (error) {
      toast.error(`Failed to create run: ${getErrorMessage(error)}`)
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4">
      <div className="relative overflow-hidden rounded-xl border bg-card/80 p-4">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-20 [mask-image:linear-gradient(to_bottom,black,transparent_82%)] dark:opacity-15"
        >
          <Aurora
            amplitude={0.42}
            blend={0.62}
            colorStops={headerAuroraStops}
            speed={0.38}
          />
        </div>
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-gradient-to-r from-card via-card/90 to-card/70"
        />
        <div className="relative flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <Badge variant="secondary">Pipeline runs</Badge>
            <h1 className="mt-3 text-2xl font-semibold tracking-normal">
              Runs
            </h1>
            <p
              className="max-w-xl truncate text-sm text-muted-foreground"
              title={API_BASE_URL}
            >
              Backend base URL: {API_BASE_URL}
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
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Card>
          <CardHeader>
            <CardTitle>Runs list</CardTitle>
            <CardDescription>Existing backend runs</CardDescription>
            <CardAction>
              <Badge variant="outline">
                {runsState.hasLoaded ? runsState.runs.length : "..."}
              </Badge>
            </CardAction>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {!runsState.hasLoaded ? (
                  <RunListSkeletonRows />
                ) : runsState.runs.length === 0 ? (
                  <TableRow>
                    <TableCell
                      className="py-8 text-center text-muted-foreground"
                      colSpan={4}
                    >
                      {runsState.error ?? "No runs yet."}
                    </TableCell>
                  </TableRow>
                ) : (
                  runsState.runs.map((run, index) => {
                    const paramsSummary = summarizeRunParams(run)
                    const runHref = `/runs/${run.id}`

                    return (
                      <motion.tr
                        animate={{ opacity: 1, y: 0 }}
                        className="group cursor-pointer border-b transition-[background-color,box-shadow,transform] duration-200 hover:-translate-y-px hover:bg-muted/45 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                        data-slot="table-row"
                        initial={
                          shouldReduceMotion ? false : { opacity: 0, y: 8 }
                        }
                        key={run.id}
                        onClick={() => navigate(runHref)}
                        onKeyDown={(event) =>
                          handleRunRowKeyDown(event, () => navigate(runHref))
                        }
                        role="link"
                        tabIndex={0}
                        transition={{
                          delay: shouldReduceMotion
                            ? 0
                            : Math.min(index * 0.025, 0.16),
                          duration: shouldReduceMotion ? 0 : 0.22,
                          ease: "easeOut",
                        }}
                      >
                        <TableCell>
                          <div className="min-w-0">
                            <span
                              className="block max-w-[16rem] truncate font-medium text-foreground group-hover:underline"
                              title={run.id}
                            >
                              {shortRunId(run.id)}
                            </span>
                            <div
                              className="mt-0.5 max-w-[34rem] truncate text-xs text-muted-foreground"
                              title={paramsSummary}
                            >
                              {paramsSummary}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={run.status} />
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          <span title={formatDateTime(run.created_at)}>
                            {formatRelativeTime(run.created_at)}
                          </span>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            asChild
                            onClick={(event) => event.stopPropagation()}
                            size="sm"
                            variant="outline"
                          >
                            <Link to={runHref}>Open</Link>
                          </Button>
                        </TableCell>
                      </motion.tr>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card className="h-fit bg-card/95">
          <CardHeader>
            <CardTitle>New run</CardTitle>
            <CardDescription>Start a five-step evidence pipeline</CardDescription>
            <CardAction>
              <Badge variant="secondary">5 steps</Badge>
            </CardAction>
          </CardHeader>
          <CardContent>
            <form className="space-y-3" onSubmit={handleSubmit}>
              <div className="space-y-1.5">
                <label className="text-xs font-medium" htmlFor="keywords">
                  Keywords
                </label>
                <Input
                  id="keywords"
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      keywords: event.target.value,
                    }))
                  }
                  placeholder="mpox serial interval infectiousness"
                  required
                  value={form.keywords}
                />
              </div>
              <div className="space-y-1.5">
                <label
                  className="text-xs font-medium"
                  htmlFor="research_question"
                >
                  Research question
                </label>
                <Textarea
                  className="min-h-28 resize-none"
                  id="research_question"
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      research_question: event.target.value,
                    }))
                  }
                  placeholder="Among eligible mpox studies, what serial interval estimates and uncertainty should be pooled?"
                  required
                  value={form.research_question}
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium" htmlFor="disease">
                    Disease
                  </label>
                  <select
                    className={selectClassName}
                    id="disease"
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        disease: event.target.value as RunFormState["disease"],
                      }))
                    }
                    value={form.disease}
                  >
                    {diseaseOptions.map((disease) => (
                      <option key={disease} value={disease}>
                        {disease}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium" htmlFor="parameter">
                    Parameter
                  </label>
                  <select
                    className={selectClassName}
                    id="parameter"
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        parameter: event.target
                          .value as RunFormState["parameter"],
                      }))
                    }
                    value={form.parameter}
                  >
                    {parameterOptions.map((parameter) => (
                      <option key={parameter} value={parameter}>
                        {parameter}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <Separator />
              <Button className="w-full" disabled={!canCreate} type="submit">
                {isCreating ? (
                  <LoaderCircleIcon className="motion-safe:animate-spin motion-reduce:animate-none" />
                ) : (
                  <PlayIcon />
                )}
                {isCreating ? "Creating…" : "Create run"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function RunListSkeletonRows() {
  return (
    <>
      {RUN_LIST_SKELETON_KEYS.map((key) => (
        <TableRow key={key}>
          <TableCell>
            <div className="space-y-2">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-3 w-64 max-w-full" />
            </div>
          </TableCell>
          <TableCell>
            <Skeleton className="h-5 w-20 rounded-4xl" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-4 w-24" />
          </TableCell>
          <TableCell className="text-right">
            <Skeleton className="ml-auto h-7 w-16" />
          </TableCell>
        </TableRow>
      ))}
    </>
  )
}

function handleRunRowKeyDown(
  event: KeyboardEvent<HTMLTableRowElement>,
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

function summarizeRunParams(run: Run) {
  const values = [
    stringifyParam(run.params.disease),
    stringifyParam(run.params.parameter),
    stringifyParam(run.params.keywords),
  ].filter(Boolean)

  return values.length > 0 ? values.join(" / ") : "No params"
}

function stringifyParam(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null
}

const RUN_LIST_SKELETON_KEYS = ["run-1", "run-2", "run-3", "run-4", "run-5"]
