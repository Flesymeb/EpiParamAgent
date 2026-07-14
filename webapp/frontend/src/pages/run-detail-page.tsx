import type { ReactNode } from "react"
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import {
  AlertCircleIcon,
  BarChart3Icon,
  CopyIcon,
  DownloadIcon,
  FileTextIcon,
  LoaderCircleIcon,
  PlayIcon,
  RefreshCwIcon,
  SaveIcon,
  SearchIcon,
  ScrollTextIcon,
  SlidersHorizontalIcon,
  TableIcon,
  XIcon,
  type LucideIcon,
} from "lucide-react"
import { toast } from "sonner"

import {
  artifactUrl,
  getRunEvents,
  getStepFile,
  getStepIndex,
  getStepRows,
  saveEditedStep,
  startStep,
  subscribeToRunEvents,
} from "@/api/pipeline"
import type {
  PipelineStep as StepRead,
  RunEvent,
  StepRows,
} from "@/api/pipeline"
import { EditableTable } from "@/components/editable-table"
import { EventsPanel } from "@/components/events-panel"
import { CodingSubsteps } from "@/components/coding-substeps"
import { PipelineStepper } from "@/components/pipeline-stepper"
import { RunningProgressBar, SectionCard } from "@/components/section-card"
import { StatusBadge } from "@/components/status-badge"
import { StepConfigForm } from "@/components/step-config-form"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { useRun } from "@/hooks/use-run"
import { getErrorMessage } from "@/lib/errors"
import { useSetRunHeader } from "@/lib/page-header"
import {
  getPipelineStep,
  PIPELINE_STEPS,
  resolvePipelineStepId,
} from "@/lib/pipeline"
import type { PipelineStepId } from "@/lib/pipeline"
import {
  normalizeStatus,
} from "@/lib/status"
import { cn } from "@/lib/utils"

type EventState = {
  runId: string
  events: RunEvent[]
}

type StepParamState = {
  params: Record<string, unknown>
  stepId: PipelineStepId
}

type ArtifactLoadState =
  | {
      key: string
      status: "idle" | "loading"
      text: null
      error: null
    }
  | {
      key: string
      status: "ready"
      text: string
      error: null
    }
  | {
      key: string
      status: "error"
      text: null
      error: string
    }

type RowsLoadState =
  | {
      key: string
      status: "idle" | "loading"
      data: null
      error: null
    }
  | {
      key: string
      status: "ready"
      data: StepRows
      error: null
    }
  | {
      key: string
      status: "error"
      data: null
      error: string
    }

const MISSING_ARTIFACT_MESSAGE = "Artifact file is not available yet."
const RUN_DETAIL_TABS = ["config", "run", "output", "logs"] as const
const EMPTY_EVENTS: RunEvent[] = []
const EMPTY_PARAMS: Record<string, unknown> = {}
const RUN_DETAIL_TAB_TRIGGER_CLASS =
  "min-h-8 min-w-0 gap-1 px-1 text-xs sm:gap-1.5 sm:px-2.5 sm:text-sm data-active:border-emerald-500/40 data-active:bg-emerald-500/12 data-active:text-emerald-700 data-active:ring-1 data-active:ring-emerald-500/15 data-[state=active]:border-emerald-500/40 data-[state=active]:bg-emerald-500/12 data-[state=active]:text-emerald-700 data-[state=active]:ring-1 data-[state=active]:ring-emerald-500/15 dark:data-active:border-emerald-500/45 dark:data-active:bg-emerald-500/15 dark:data-active:text-emerald-300 dark:data-[state=active]:border-emerald-500/45 dark:data-[state=active]:bg-emerald-500/15 dark:data-[state=active]:text-emerald-300"

type RunDetailTab = (typeof RUN_DETAIL_TABS)[number]

// Lazy-loaded so recharts (heavy) only loads when a pooling chart is shown,
// not on every run-detail page mount.
const PoolingResult = lazy(() =>
  import("@/components/pooling-result").then((module) => ({
    default: module.PoolingResult,
  }))
)

export function RunDetailPage() {
  const { runId = "" } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const hasExplicitStep = searchParams.has("step")
  const currentStepId = resolvePipelineStepId(searchParams.get("step"))
  const currentTab = resolveRunDetailTab(searchParams.get("tab"))
  const currentStep = getPipelineStep(currentStepId)
  const StepIcon = currentStep.icon
  // Capture/test aid: ?nosse=1 skips long-lived SSE so headless tools can settle.
  const shouldSkipEventSource =
    searchParams.get("nosse") === "1" ||
    (import.meta.env.DEV && searchParams.has("nosse"))
  const { detail, error, isLoading, refresh } = useRun(runId)
  const [startingStepNo, setStartingStepNo] = useState<number | null>(null)
  const [isRefreshingRun, setIsRefreshingRun] = useState(false)
  const [stepParamState, setStepParamState] =
    useState<StepParamState | null>(null)
  const [streamVersion, setStreamVersion] = useState(0)
  const [streamErrorKey, setStreamErrorKey] = useState<string | null>(null)
  const [eventState, setEventState] = useState<EventState>({
    runId,
    events: [],
  })
  const streamErrorReportedRef = useRef(false)

  const stepsByNumber = useMemo(() => {
    const steps = new Map<number, StepRead>()
    detail?.steps.forEach((step) => {
      steps.set(step.step_no, step)
    })
    return steps
  }, [detail])

  const stepStatuses = useMemo(() => {
    const statuses: Partial<Record<number, string>> = {}
    detail?.steps.forEach((step) => {
      statuses[step.step_no] = step.status
    })
    return statuses
  }, [detail])

  const editedStepNos = useMemo(() => {
    const stepNos = new Set<number>()
    detail?.steps.forEach((step) => {
      if (step.edited_artifact_path) {
        stepNos.add(step.step_no)
      }
    })
    return stepNos
  }, [detail])

  const selectedStep = stepsByNumber.get(currentStep.backendStep)
  const selectedStatus = normalizeStatus(selectedStep?.status)
  const selectedHasEditedArtifact = Boolean(selectedStep?.edited_artifact_path)
  const selectedArtifactPath =
    selectedStep?.edited_artifact_path ?? selectedStep?.artifact_path
  const resultArtifactPath =
    currentStep.id === "code"
      ? `data/webapp/runs/${runId}/step-${currentStep.backendStep}/index/*.index.json`
      : selectedArtifactPath
  const resultHasEditedArtifact =
    currentStep.id === "code" ? false : selectedHasEditedArtifact
  const activeStepParams =
    stepParamState?.stepId === currentStep.id
      ? stepParamState.params
      : EMPTY_PARAMS
  const inheritedRunParams = detail?.run.params ?? EMPTY_PARAMS
  const effectiveStepParams = useMemo(() => {
    const source = {
      ...inheritedRunParams,
      ...activeStepParams,
    }

    if (currentStep.codingStage) {
      return {
        ...source,
        stage:
          typeof source.stage === "string" && source.stage
            ? source.stage
            : currentStep.codingStage,
      }
    }

    return source
  }, [activeStepParams, currentStep.codingStage, inheritedRunParams])
  const codingStageInfo = getCodingStageInfo(
    currentStep.id,
    currentStep.backendStep
  )
  const events = eventState.runId === runId ? eventState.events : EMPTY_EVENTS
  const selectedStepEvents = useMemo(
    () =>
      events
        .filter((event) => event.step_no === currentStep.backendStep)
        .slice(-5)
        .reverse(),
    [currentStep.backendStep, events]
  )
  const streamKey = `${runId}:${streamVersion}`
  const isStreamConnected = !shouldSkipEventSource && streamErrorKey !== streamKey
  const eventConnectionStatus = shouldSkipEventSource
    ? "paused"
    : isStreamConnected
      ? "live"
      : "offline"
  const anyStepRunning =
    detail?.steps.some((step) => normalizeStatus(step.status) === "running") ??
    false
  const isSelectedStepRunning =
    selectedStatus === "running" || startingStepNo === currentStep.backendStep

  useEffect(() => {
    if (error) {
      toast.error(`Failed to load run: ${error}`)
    }
  }, [error])

  useEffect(() => {
    if (!detail || hasExplicitStep) {
      return
    }

    const defaultStepId = getDefaultPipelineStepId(detail.steps)
    if (defaultStepId === currentStepId) {
      return
    }

    setSearchParams(
      (current) => {
        if (current.has("step")) {
          return current
        }

        const next = new URLSearchParams(current)
        next.set("step", defaultStepId)
        return next
      },
      { replace: true }
    )
  }, [currentStepId, detail, hasExplicitStep, setSearchParams])

  useEffect(() => {
    if (!runId) {
      return
    }

    const controller = new AbortController()
    void getRunEvents(runId, { signal: controller.signal })
      .then((history) => {
        setEventState((current) => {
          const currentEvents = current.runId === runId ? current.events : []
          return {
            runId,
            events: mergeRunEvents(currentEvents, history),
          }
        })
      })
      .catch((historyError) => {
        if (!controller.signal.aborted) {
          toast.error(
            `Failed to load run events: ${getErrorMessage(historyError)}`
          )
        }
      })

    return () => {
      controller.abort()
    }
  }, [runId])

  useEffect(() => {
    if (!runId) {
      return
    }

    if (shouldSkipEventSource) {
      return
    }

    const controller = new AbortController()
    streamErrorReportedRef.current = false

    const close = subscribeToRunEvents(runId, {
      signal: controller.signal,
      onEvent: (event) => {
        setStreamErrorKey(null)
        setEventState((current) => {
          const currentEvents = current.runId === runId ? current.events : []
          if (currentEvents.some((candidate) => candidate.id === event.id)) {
            return current.runId === runId
              ? current
              : { runId, events: currentEvents }
          }

          return { runId, events: mergeRunEvents(currentEvents, [event]) }
        })

        if (eventIndicatesStepRefresh(event)) {
          void refresh().catch((refreshError) => {
            toast.error(`Failed to refresh run: ${getErrorMessage(refreshError)}`)
          })
        }
      },
      onError: () => {
        setStreamErrorKey(streamKey)
        if (!streamErrorReportedRef.current) {
          streamErrorReportedRef.current = true
          toast.error("Live events stream disconnected")
        }
      },
    })

    return () => {
      controller.abort()
      close()
    }
  }, [refresh, runId, shouldSkipEventSource, streamKey])

  useSetRunHeader(
    runId
      ? {
          runId,
          status: detail?.run.status,
          stepRunning: anyStepRunning,
          paramsSummary: detail
            ? summarizeRunParams(detail.run.params)
            : "Loading run…",
        }
      : null
  )

  function handleStepChange(nextStepId: PipelineStepId) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set("step", nextStepId)
      return next
    })
  }

  function handleTabChange(nextValue: string) {
    const nextTab = resolveRunDetailTab(nextValue)
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set("tab", nextTab)
      return next
    })
  }

  async function handleStartStep() {
    if (!runId) {
      return
    }

    setStartingStepNo(currentStep.backendStep)
    setStreamVersion((current) => current + 1)

    try {
      await startStep(runId, currentStep.backendStep, effectiveStepParams)
      await refresh()
    } catch (startError) {
      toast.error(
        `Failed to start ${currentStep.label}: ${getErrorMessage(
          startError
        )}`
      )
    } finally {
      setStartingStepNo(null)
    }
  }

  async function handleManualRefresh() {
    setIsRefreshingRun(true)

    try {
      await refresh()
    } catch (refreshError) {
      toast.error(`Failed to refresh run: ${getErrorMessage(refreshError)}`)
    } finally {
      setIsRefreshingRun(false)
    }
  }

  if (!runId) {
    return (
      <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Run not found</CardTitle>
            <CardDescription>Missing run id.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild variant="outline">
              <Link to="/">Back to runs</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (isLoading) {
    return <RunDetailSkeleton />
  }

  if (error && !detail) {
    return (
      <RunDetailError
        error={error}
        onRefresh={() => {
          void refresh().catch((refreshError) => {
            toast.error(`Failed to refresh run: ${getErrorMessage(refreshError)}`)
          })
        }}
      />
    )
  }

  return (
    <div className="mx-auto flex w-full min-w-0 max-w-[1500px] flex-1 flex-col gap-4 overflow-x-hidden sm:gap-5">
      <Card className="relative gap-0 overflow-hidden py-0">
        {anyStepRunning ? <RunningProgressBar /> : null}
        <div className="flex items-center justify-between gap-2 border-b bg-muted/20 px-3 py-2 sm:px-4 sm:py-2.5">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">Pipeline</span>
            <Badge className="font-normal" variant="outline">
              Step {currentStep.number} of {PIPELINE_STEPS.length}
            </Badge>
          </div>
          <Button
            aria-busy={isRefreshingRun}
            className="h-8"
            disabled={isRefreshingRun}
            onClick={() => {
              void handleManualRefresh()
            }}
            size="sm"
            variant="ghost"
          >
            <RefreshCwIcon
              className={cn(
                isRefreshingRun &&
                  "motion-safe:animate-spin motion-reduce:animate-none"
              )}
            />
            Refresh
          </Button>
        </div>
        <div className="px-1 py-2 sm:px-2 sm:py-3">
          <PipelineStepper
            currentStepId={currentStepId}
            editedStepNos={editedStepNos}
            onStepChange={handleStepChange}
            stepStatuses={stepStatuses}
          />
        </div>
      </Card>

      <Tabs
        className="w-full min-w-0 flex-1 gap-3 overflow-hidden sm:gap-4"
        onValueChange={handleTabChange}
        value={currentTab}
      >
        <div className="flex flex-col gap-2 xl:flex-row xl:items-start xl:justify-between xl:gap-3">
          <div className="flex min-w-0 flex-1 items-start gap-2 sm:gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-card text-primary shadow-sm sm:size-10 sm:rounded-xl">
              <StepIcon className="size-4 sm:size-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-semibold leading-tight tracking-tight sm:text-lg">
                {currentStep.number}. {currentStep.label}
              </h2>
              <p className="mt-0.5 text-xs leading-4 text-muted-foreground sm:mt-1 sm:text-sm sm:leading-5">
                {currentStep.description}
              </p>
            </div>
          </div>
          <div className="grid w-full shrink-0 gap-1 md:flex md:flex-wrap md:items-center md:justify-between md:gap-2 xl:w-auto xl:justify-end">
            <div className="flex min-w-0 items-center gap-1.5 sm:gap-2">
              {selectedHasEditedArtifact ? (
                <Badge variant="secondary">edited</Badge>
              ) : null}
              <StatusBadge status={selectedStep?.status} />
            </div>
            <div className="min-w-0 max-w-full sm:mx-0 sm:px-0">
              <TabsList className="grid h-auto min-h-10 w-full grid-cols-2 border border-border/70 bg-muted/35 shadow-xs group-data-horizontal/tabs:h-auto min-[360px]:grid-cols-4 sm:inline-flex sm:w-max sm:grid-cols-none">
                <TabsTrigger className={RUN_DETAIL_TAB_TRIGGER_CLASS} value="config">
                  <SlidersHorizontalIcon className="size-3.5 sm:size-4" />
                  Config
                </TabsTrigger>
                <TabsTrigger className={RUN_DETAIL_TAB_TRIGGER_CLASS} value="run">
                  <PlayIcon className="size-3.5 sm:size-4" />
                  Run
                </TabsTrigger>
                <TabsTrigger className={RUN_DETAIL_TAB_TRIGGER_CLASS} value="output">
                  <FileTextIcon className="size-3.5 sm:size-4" />
                  Output
                </TabsTrigger>
                <TabsTrigger
                  aria-label={
                    events.length > 0
                      ? `Logs, ${formatEventCount(events.length)}`
                      : "Logs"
                  }
                  className={RUN_DETAIL_TAB_TRIGGER_CLASS}
                  value="logs"
                >
                  <ScrollTextIcon className="size-3.5 sm:size-4" />
                  Logs
                  {events.length > 0 ? (
                    <>
                      {" "}
                      <span
                        aria-hidden="true"
                        className="ml-1 rounded-full border border-border/70 bg-background px-1.5 text-[0.65rem] leading-4 text-muted-foreground"
                      >
                        {events.length}
                      </span>
                    </>
                  ) : null}
                </TabsTrigger>
              </TabsList>
            </div>
          </div>
        </div>
        <TabsContent className="min-w-0 max-w-full overflow-hidden" value="config">
          <StepConfigForm
            disabled={isSelectedStepRunning}
            initialValues={detail?.run.params ?? {}}
            key={currentStep.number}
            onChange={(params) => {
              setStepParamState({ params, stepId: currentStep.id })
            }}
            stepNumber={currentStep.number}
          />
        </TabsContent>
        <TabsContent className="min-w-0 max-w-full overflow-hidden" value="run">
          <div className="min-w-0 space-y-3">
            <SectionCard
              icon={PlayIcon}
              running={isSelectedStepRunning}
              title="Execution"
            >
              <div className="space-y-3 sm:space-y-4">
                <div className="min-w-0 space-y-3 sm:space-y-4">
                  {currentStep.backendStep === 4 ? (
                    <>
                      {codingStageInfo ? (
                        <CodingStageContext
                          badgeLabel={codingStageInfo.badgeLabel}
                          description={codingStageInfo.description}
                          icon={StepIcon}
                          title={codingStageInfo.title}
                        />
                      ) : null}
                      <CodingSubsteps
                        events={events}
                        stage={String(effectiveStepParams.stage ?? "extract")}
                        status={selectedStatus}
                      />
                    </>
                  ) : null}
                  <dl className="grid gap-2 sm:gap-3">
                    <div className="min-w-0 border-l border-border pl-2.5 sm:pl-3">
                      <dt className="text-[0.68rem] font-medium leading-4 text-muted-foreground sm:text-xs">
                        Last activity
                      </dt>
                      <dd
                        className="mt-0.5 truncate text-sm sm:mt-1"
                        title={formatStepTiming(selectedStep)}
                      >
                        {formatStepTiming(selectedStep)}
                      </dd>
                    </div>
                    <div className="min-w-0 border-l border-border pl-2.5 sm:pl-3">
                      <dt className="text-[0.68rem] font-medium leading-4 text-muted-foreground sm:text-xs">
                        Step status
                      </dt>
                      <dd className="mt-0.5 sm:mt-1">
                        <StatusBadge status={selectedStep?.status} />
                      </dd>
                    </div>
                  </dl>
                </div>
                <div className="flex">
                  <Button
                    aria-busy={isSelectedStepRunning}
                    className="w-full sm:w-auto"
                    disabled={isLoading || isSelectedStepRunning}
                    onClick={() => {
                      void handleStartStep()
                    }}
                  >
                    {isSelectedStepRunning ? (
                      <LoaderCircleIcon className="motion-safe:animate-spin motion-reduce:animate-none" />
                    ) : (
                      <PlayIcon />
                    )}
                    {isSelectedStepRunning
                      ? "Running…"
                      : `Run ${currentStep.label}`}
                  </Button>
                </div>
              </div>
            </SectionCard>
            <ResultStatusPreview
              artifactBadgeLabel={codingStageInfo?.artifactBadgeLabel}
              artifactPath={resultArtifactPath}
              hasEditedArtifact={resultHasEditedArtifact}
              onViewOutput={() => handleTabChange("output")}
              readyMessage={codingStageInfo?.readyMessage}
              status={selectedStep?.status}
            />
            <StepEventPreview
              events={selectedStepEvents}
              onViewLogs={() => handleTabChange("logs")}
              stepNo={currentStep.backendStep}
              totalEventCount={events.length}
            />
            <RunParametersPreview
              onEdit={() => handleTabChange("config")}
              params={effectiveStepParams}
            />
          </div>
        </TabsContent>
        <TabsContent className="min-w-0 max-w-full overflow-hidden" value="output">
          <SectionCard
            icon={FileTextIcon}
            title={codingStageInfo?.outputTitle ?? "Output"}
          >
            <ArtifactPreview
              artifactPath={selectedArtifactPath}
              hasEditedArtifact={selectedHasEditedArtifact}
              onSaved={refresh}
              runId={runId}
              stageId={currentStep.id}
              stepNo={currentStep.backendStep}
              stepStatus={selectedStep?.status}
            />
          </SectionCard>
        </TabsContent>
        <TabsContent className="min-w-0 max-w-full overflow-hidden" value="logs">
          <EventsPanel
            connectionStatus={eventConnectionStatus}
            events={events}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function RunDetailSkeleton() {
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-5">
      <Card className="gap-0 overflow-hidden py-0">
        <div className="flex items-center justify-between gap-2 border-b bg-muted/20 px-4 py-2.5">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-8 w-20" />
        </div>
        <div className="px-2 py-3">
          <div className="w-full overflow-hidden">
            <div className="mx-auto flex w-max items-start py-1">
              {PIPELINE_SKELETON_KEYS.map((key, index) => (
                <div
                  className="relative flex w-24 flex-none flex-col items-center gap-1.5"
                  key={key}
                >
                  {index > 0 ? (
                    <Skeleton className="absolute left-[-28px] top-5 h-px w-[56px]" />
                  ) : null}
                  <Skeleton className="size-10 rounded-full" />
                  <Skeleton className="h-3 w-14" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </Card>
      <div className="flex flex-1 flex-col gap-2">
        <Skeleton className="h-9 w-44" />
        <Card className="min-h-[520px]">
          <CardHeader>
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-72 max-w-full" />
          </CardHeader>
          <CardContent className="space-y-4">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-[280px] w-full" />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function RunDetailError({
  error,
  onRefresh,
}: {
  error: string
  onRefresh: () => void
}) {
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertCircleIcon className="size-4 text-destructive" />
            Unable to load run
          </CardTitle>
          <CardDescription>{error}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button onClick={onRefresh}>
            <RefreshCwIcon />
            Try again
          </Button>
          <Button asChild variant="outline">
            <Link to="/">Back to runs</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

function getCodingStageInfo(stepId: PipelineStepId, backendStep: number) {
  if (stepId === "code") {
    return {
      artifactBadgeLabel: "structured index",
      badgeLabel: `backend step ${backendStep}`,
      description:
        "Evidence map view from the coding run. Extraction uses this same backend step.",
      outputTitle: "Structured index",
      readyMessage:
        "Step is done; open Output to load the structured index preview.",
      title: "Structured index view",
    }
  }

  if (stepId === "extract") {
    return {
      artifactBadgeLabel: "coding sheet",
      badgeLabel: `backend step ${backendStep}`,
      description:
        "Extracted-value view from the same coding run that produces the index.",
      outputTitle: "Coding sheet",
      readyMessage:
        "Coding sheet is available from the same coding run as the structured index.",
      title: "Coding sheet view",
    }
  }

  return null
}

function CodingStageContext({
  badgeLabel,
  description,
  icon: Icon,
  title,
}: {
  badgeLabel: string
  description: string
  icon: LucideIcon
  title: string
}) {
  return (
    <div className="min-w-0 border-l border-primary/35 bg-primary/[0.035] px-2.5 py-2 sm:px-3">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Icon className="size-3.5 shrink-0 text-primary" />
        <span className="min-w-0 text-sm font-medium leading-5">{title}</span>
        <Badge
          className="h-5 rounded-full px-1.5 text-[0.65rem] font-normal"
          variant="outline"
        >
          {badgeLabel}
        </Badge>
      </div>
      <div className="mt-1 text-xs leading-5 text-muted-foreground">
        {description}
      </div>
    </div>
  )
}

function StepEventPreview({
  events,
  onViewLogs,
  stepNo,
  totalEventCount,
}: {
  events: RunEvent[]
  onViewLogs: () => void
  stepNo: number
  totalEventCount: number
}) {
  const hasRunLevelEvents = totalEventCount > 0

  return (
    <SectionCard
      action={
        <Button onClick={onViewLogs} size="sm" type="button" variant="ghost">
          View logs
        </Button>
      }
      icon={ScrollTextIcon}
      title="Recent step events"
    >
      {events.length === 0 ? (
        <div className="flex min-h-20 items-center justify-center rounded-lg border border-dashed bg-muted/25 p-3 text-center sm:min-h-28 sm:p-4">
          <div className="max-w-sm text-xs leading-5 text-muted-foreground sm:text-sm">
            {hasRunLevelEvents
              ? `No step-specific events for step ${stepNo} yet. Logs has ${formatEventCount(totalEventCount)} for the full run.`
              : `No events for step ${stepNo} yet. Run the step or open Logs for the full run stream.`}
          </div>
        </div>
      ) : (
        <div className="min-w-0 space-y-2">
          {events.map((event) => {
            const level = getEventLevelStyle(event.level)

            return (
              <div
                className="grid min-w-0 grid-cols-[auto_1fr] gap-3 rounded-md bg-muted/15 px-3 py-2 text-sm"
                key={event.id}
              >
                <span
                  aria-hidden="true"
                  className={cn("mt-2 size-2 rounded-full", level.dotClassName)}
                />
                <div className="min-w-0">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <Badge
                      className={cn("border uppercase", level.badgeClassName)}
                      variant="outline"
                    >
                      {level.label}
                    </Badge>
                    <span
                      className="text-xs text-muted-foreground"
                      title={formatDateTime(event.ts)}
                    >
                      {formatEventTime(event.ts)}
                    </span>
                  </div>
                  <p className="mt-1 break-words text-foreground">
                    {event.message}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </SectionCard>
  )
}

function RunParametersPreview({
  onEdit,
  params,
}: {
  onEdit: () => void
  params: Record<string, unknown>
}) {
  const entries = getDisplayParamEntries(params)

  return (
    <SectionCard
      action={
        <Button onClick={onEdit} size="sm" type="button" variant="ghost">
          Edit config
        </Button>
      }
      icon={SlidersHorizontalIcon}
      title="Run parameters"
    >
      {entries.length === 0 ? (
        <div className="flex min-h-24 items-center justify-center rounded-lg border border-dashed bg-muted/25 p-4 text-center">
          <div className="max-w-sm text-sm text-muted-foreground">
            No parameters are set for this step.
          </div>
        </div>
      ) : (
        <div className="min-w-0 overflow-hidden rounded-lg border border-border/60 bg-muted/10">
          {entries.map((entry) => (
            <div
              className="min-w-0 space-y-0.5 border-b border-border/60 px-2 py-2 last:border-b-0 sm:grid sm:grid-cols-[minmax(8rem,0.32fr)_minmax(0,1fr)] sm:items-start sm:gap-2 sm:space-y-0 sm:px-3"
              key={entry.key}
            >
              <div className="min-w-0 whitespace-normal text-[0.65rem] font-medium uppercase leading-4 text-muted-foreground sm:truncate sm:text-[0.68rem] sm:leading-5">
                {formatStatLabel(entry.key)}
              </div>
              <div
                className="min-w-0 line-clamp-2 font-mono text-xs leading-5 text-foreground [overflow-wrap:anywhere] sm:line-clamp-none"
                title={entry.value}
              >
                {entry.value}
              </div>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  )
}

function ResultStatusPreview({
  artifactBadgeLabel,
  artifactPath,
  hasEditedArtifact,
  onViewOutput,
  readyMessage,
  status,
}: {
  artifactBadgeLabel?: string
  artifactPath: string | null | undefined
  hasEditedArtifact: boolean
  onViewOutput: () => void
  readyMessage?: string
  status: string | null | undefined
}) {
  const normalizedStatus = normalizeStatus(status)
  const hasResult = normalizedStatus === "done" && Boolean(artifactPath)
  const badgeLabel =
    artifactBadgeLabel ??
    (hasEditedArtifact ? "edited artifact" : "original artifact")

  return (
    <SectionCard
      action={
        <Button
          disabled={!hasResult}
          onClick={onViewOutput}
          size="sm"
          type="button"
          variant={hasResult ? "ghost" : "outline"}
        >
          View output
        </Button>
      }
      icon={FileTextIcon}
      title="Result status"
    >
      <div className="min-w-0 space-y-2 sm:space-y-3">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={status} />
            {hasResult ? (
              <Badge variant={hasEditedArtifact ? "secondary" : "outline"}>
                {badgeLabel}
              </Badge>
            ) : null}
          </div>
          <div className="text-xs leading-5 text-muted-foreground sm:text-sm">
            {hasResult
              ? readyMessage ?? "Output is available for this step."
              : normalizedStatus === "done"
                ? "Step is done, but no artifact path was reported."
                : "Output will appear after this step finishes."}
          </div>
        </div>
        <div
          className="min-w-0 rounded-md border border-border/60 bg-muted/15 px-2 py-1.5 font-mono text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere] sm:truncate sm:px-3 sm:py-2"
          title={artifactPath ?? "No artifact path"}
        >
          {artifactPath ?? "No artifact path"}
        </div>
      </div>
    </SectionCard>
  )
}

const PIPELINE_SKELETON_KEYS = [
  "query",
  "retrieve",
  "screen",
  "code",
  "extract",
  "analyze",
]

function ArtifactPreview({
  artifactPath,
  hasEditedArtifact,
  onSaved,
  runId,
  stageId,
  stepNo,
  stepStatus,
}: {
  artifactPath: string | null | undefined
  hasEditedArtifact: boolean
  onSaved: () => Promise<unknown>
  runId: string
  stageId: PipelineStepId
  stepNo: number
  stepStatus: string | null | undefined
}) {
  const normalizedStatus = normalizeStatus(stepStatus)

  if (normalizedStatus !== "done") {
    return (
      <EmptyArtifactState
        icon={<FileTextIcon className="size-5" />}
        message="Result appears after this stage finishes."
      />
    )
  }

  // Code stage surfaces the per-paper structured index (read-only); the coding
  // run that produces it lives on the same backend step as Extraction.
  if (stageId === "code") {
    return <CodeIndexPreview runId={runId} stepNo={stepNo} />
  }

  if (!artifactPath) {
    return (
      <EmptyArtifactState
        icon={<FileTextIcon className="size-5" />}
        message="Stage is done, but no artifact path was reported."
      />
    )
  }

  if (stepNo === 1 || stepNo === 3 || stepNo === 4 || stepNo === 5) {
    return (
      <StructuredArtifactPreview
        artifactPath={artifactPath}
        hasEditedArtifact={hasEditedArtifact}
        onSaved={onSaved}
        runId={runId}
        stepNo={stepNo}
      />
    )
  }

  return (
    <TextArtifactPreview
      artifactPath={artifactPath}
      hasEditedArtifact={hasEditedArtifact}
      runId={runId}
      stepNo={stepNo}
    />
  )
}

function CodeIndexPreview({
  runId,
  stepNo,
}: {
  runId: string
  stepNo: number
}) {
  const [state, setState] = useState<RowsLoadState>({
    key: "",
    status: "idle",
    data: null,
    error: null,
  })
  const key = `${runId}:${stepNo}:index`
  const visibleState =
    state.key === key
      ? state
      : ({
          key,
          status: "loading",
          data: null,
          error: null,
        } satisfies RowsLoadState)

  useEffect(() => {
    const controller = new AbortController()

    getStepIndex(runId, stepNo, controller.signal)
      .then((data) => {
        setState({ key, status: "ready", data, error: null })
      })
      .catch((error) => {
        if (controller.signal.aborted) {
          return
        }
        setState({
          key,
          status: "error",
          data: null,
          error: getErrorMessage(error),
        })
      })

    return () => {
      controller.abort()
    }
  }, [key, runId, stepNo])

  if (visibleState.status === "loading" || visibleState.status === "idle") {
    return <ArtifactLoadingState message="Loading structured index" />
  }

  if (visibleState.status === "error") {
    return (
      <EmptyArtifactState
        icon={<TableIcon className="size-5" />}
        message="No structured index yet — run the Code stage to produce it."
      />
    )
  }

  if (visibleState.status !== "ready") {
    return null
  }

  const data = visibleState.data
  if (data.kind !== "table") {
    return <PlainTextPreview text={JSON.stringify(data, null, 2)} />
  }

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="rounded-lg border border-border/70 bg-muted/15 px-3 py-2.5">
        <div className="text-sm font-medium">Structured index</div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          Per-paper evidence map for {data.rows.length} papers. Read-only
          preview of the coding index.
        </div>
      </div>
      <div className="order-2">
        <TableSummaryPanel columns={data.columns} rows={data.rows} />
      </div>
      <div className="order-3">
        <ReadonlyTablePreview
          columns={data.columns}
          rows={data.rows}
          searchPlaceholder="Search papers"
        />
      </div>
    </div>
  )
}

function TextArtifactPreview({
  artifactPath,
  hasEditedArtifact,
  runId,
  stepNo,
}: {
  artifactPath: string
  hasEditedArtifact: boolean
  runId: string
  stepNo: number
}) {
  const [state, setState] = useState<ArtifactLoadState>({
    key: "",
    status: "idle",
    text: null,
    error: null,
  })
  const artifactKey = `${runId}:${stepNo}:${artifactPath}`
  const visibleState =
    state.key === artifactKey
      ? state
      : ({
          key: artifactKey,
          status: "loading",
          text: null,
          error: null,
        } satisfies ArtifactLoadState)

  useEffect(() => {
    const controller = new AbortController()

    async function loadArtifact() {
      try {
        const response = await fetch(artifactUrl(runId, stepNo), {
          signal: controller.signal,
        })
        if (!response.ok) {
          throw new Error(
            response.status === 404
              ? MISSING_ARTIFACT_MESSAGE
              : `Artifact request failed with ${response.status}`
          )
        }
        const text = await response.text()
        setState({
          key: artifactKey,
          status: "ready",
          text,
          error: null,
        })
      } catch (error) {
        if (controller.signal.aborted) {
          return
        }
        const message = getErrorMessage(error)
        setState({
          key: artifactKey,
          status: "error",
          text: null,
          error: message,
        })
        if (!isMissingArtifactMessage(message)) {
          toast.error(`Failed to load artifact: ${message}`)
        }
      }
    }

    void loadArtifact()

    return () => {
      controller.abort()
    }
  }, [artifactKey, runId, stepNo])

  if (visibleState.status === "loading" || visibleState.status === "idle") {
    return <ArtifactLoadingState message="Loading artifact preview" />
  }

  if (visibleState.status === "error") {
    return (
      <EmptyArtifactState
        icon={<FileTextIcon className="size-5" />}
        message={visibleState.error}
      />
    )
  }

  if (visibleState.status !== "ready") {
    return null
  }

  return (
    <div className="min-w-0 space-y-3">
      <ArtifactPathLabel
        artifactPath={artifactPath}
        hasEditedArtifact={hasEditedArtifact}
        runId={runId}
        stepNo={stepNo}
      />
      <ArtifactBody
        artifactPath={artifactPath}
        stepNo={stepNo}
        text={visibleState.text}
      />
    </div>
  )
}

function StructuredArtifactPreview({
  artifactPath,
  hasEditedArtifact,
  onSaved,
  runId,
  stepNo,
}: {
  artifactPath: string
  hasEditedArtifact: boolean
  onSaved: () => Promise<unknown>
  runId: string
  stepNo: number
}) {
  const [state, setState] = useState<RowsLoadState>({
    key: "",
    status: "idle",
    data: null,
    error: null,
  })
  const artifactKey = `${runId}:${stepNo}:${artifactPath}`
  const visibleState =
    state.key === artifactKey
      ? state
      : ({
          key: artifactKey,
          status: "loading",
          data: null,
          error: null,
        } satisfies RowsLoadState)

  useEffect(() => {
    let active = true

    async function loadRows() {
      try {
        const data = await getStepRows(runId, stepNo)
        if (active) {
          setState({
            key: artifactKey,
            status: "ready",
            data,
            error: null,
          })
        }
      } catch (error) {
        if (!active) {
          return
        }
        const message = getErrorMessage(error)
        setState({
          key: artifactKey,
          status: "error",
          data: null,
          error: isMissingArtifactMessage(message)
            ? MISSING_ARTIFACT_MESSAGE
            : message,
        })
        if (!isMissingArtifactMessage(message)) {
          toast.error(`Failed to load artifact rows: ${message}`)
        }
      }
    }

    void loadRows()

    return () => {
      active = false
    }
  }, [artifactKey, runId, stepNo])

  if (visibleState.status === "loading" || visibleState.status === "idle") {
    return <ArtifactLoadingState message="Loading artifact rows" />
  }

  if (visibleState.status === "error") {
    return (
      <EmptyArtifactState
        icon={<FileTextIcon className="size-5" />}
        message={visibleState.error}
      />
    )
  }

  if (visibleState.status !== "ready") {
    return null
  }

  return (
    <div className="min-w-0 space-y-3">
      <ArtifactPathLabel
        artifactPath={artifactPath}
        hasEditedArtifact={hasEditedArtifact}
        runId={runId}
        stepNo={stepNo}
      />
      <StructuredArtifactBody
        artifactKey={artifactKey}
        data={visibleState.data}
        onSaved={onSaved}
        runId={runId}
        stepNo={stepNo}
      />
    </div>
  )
}

function isMissingArtifactMessage(message: string) {
  const normalized = message.toLowerCase().replace(/\s+/g, "")

  return (
    normalized.includes("artifactfileisnotavailableyet") ||
    normalized.includes("stepartifactisabsent") ||
    normalized.includes("stepartifactfilenotfound") ||
    normalized.includes("artifactrequestfailedwith404")
  )
}

function ArtifactPathLabel({
  artifactPath,
  hasEditedArtifact,
  runId,
  stepNo,
}: {
  artifactPath: string
  hasEditedArtifact: boolean
  runId: string
  stepNo: number
}) {
  async function handleCopyPath() {
    try {
      await navigator.clipboard.writeText(artifactPath)
      toast.success("Artifact path copied")
    } catch (error) {
      toast.error(`Failed to copy path: ${getErrorMessage(error)}`)
    }
  }

  return (
    <div className="flex flex-col items-stretch gap-2 rounded-lg border border-border/70 bg-muted/15 px-2.5 py-2 text-sm sm:flex-row sm:items-center sm:px-3 sm:py-2.5">
      <div className="flex min-w-0 w-full items-start gap-1.5 font-medium sm:flex-1 sm:items-center sm:gap-2">
        <FileTextIcon className="size-3.5 shrink-0 text-muted-foreground sm:size-4" />
        <span
          className="min-w-0 flex-1 line-clamp-2 leading-5 [overflow-wrap:anywhere] sm:truncate"
          title={artifactPath}
        >
          {artifactPath}
        </span>
      </div>
      <div className="flex shrink-0 items-center justify-between gap-2 sm:justify-start">
        <Badge className="shrink-0" variant={hasEditedArtifact ? "secondary" : "outline"}>
          {hasEditedArtifact ? "edited" : "original"}
        </Badge>
        <div className="flex items-center gap-1 sm:gap-1.5">
          <Button
            aria-label="Copy artifact path"
            className="size-8 px-0 sm:size-auto sm:px-2.5"
            onClick={() => {
              void handleCopyPath()
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            <CopyIcon />
            <span className="sr-only sm:not-sr-only">Copy</span>
          </Button>
          <Button
            asChild
            className="size-8 px-0 sm:size-auto sm:px-2.5"
            size="sm"
            variant="outline"
          >
            <a
              aria-label="Download artifact"
              download
              href={artifactUrl(runId, stepNo)}
            >
              <DownloadIcon />
              <span className="sr-only sm:not-sr-only">Download</span>
            </a>
          </Button>
        </div>
      </div>
    </div>
  )
}

function ArtifactBody({
  artifactPath,
  stepNo,
  text,
}: {
  artifactPath: string
  stepNo: number
  text: string
}) {
  const lowerPath = artifactPath.toLowerCase()

  if (lowerPath.endsWith("pooled.csv") || stepNo === 5) {
    return <PooledCsvPreview text={text} />
  }

  if (lowerPath.endsWith(".csv")) {
    return <CsvTablePreview text={text} />
  }

  if (lowerPath.endsWith(".json")) {
    return <JsonTextPreview text={text} />
  }

  return <PlainTextPreview text={text} />
}

function StructuredArtifactBody({
  artifactKey,
  data,
  onSaved,
  runId,
  stepNo,
}: {
  artifactKey: string
  data: StepRows
  onSaved: () => Promise<unknown>
  runId: string
  stepNo: number
}) {
  if (data.kind === "json") {
    if (stepNo === 1) {
      return (
        <QueryArtifactEditor
          key={artifactKey}
          data={data.data}
          onSaved={onSaved}
          runId={runId}
          stepNo={stepNo}
        />
      )
    }

    return <JsonTextPreview text={JSON.stringify(data.data, null, 2)} />
  }

  if (data.kind === "table" && stepNo === 5) {
    return (
      <PoolingArtifactBody
        pooledRows={data}
        runId={runId}
        stepNo={stepNo}
      />
    )
  }

  if (data.kind === "table" && (stepNo === 3 || stepNo === 4)) {
    return (
      <EditableCsvArtifact
        key={artifactKey}
        columns={data.columns}
        onSaved={onSaved}
        rows={data.rows}
        runId={runId}
        stepNo={stepNo}
      />
    )
  }

  return <PlainTextPreview text={JSON.stringify(data, null, 2)} />
}

function PoolingArtifactBody({
  pooledRows,
  runId,
  stepNo,
}: {
  pooledRows: Extract<StepRows, { kind: "table" }>
  runId: string
  stepNo: number
}) {
  const [state, setState] = useState<RowsLoadState>({
    key: "",
    status: "idle",
    data: null,
    error: null,
  })
  const artifactKey = `${runId}:${stepNo}:forest.csv`
  const visibleState =
    state.key === artifactKey
      ? state
      : ({
          key: artifactKey,
          status: "loading",
          data: null,
          error: null,
        } satisfies RowsLoadState)

  useEffect(() => {
    let active = true

    async function loadForestRows() {
      try {
        const data = await getStepFile(runId, stepNo, "forest.csv")
        if (active) {
          setState({
            key: artifactKey,
            status: "ready",
            data,
            error: null,
          })
        }
      } catch (error) {
        if (active) {
          setState({
            key: artifactKey,
            status: "error",
            data: null,
            error: getErrorMessage(error),
          })
        }
      }
    }

    void loadForestRows()

    return () => {
      active = false
    }
  }, [artifactKey, runId, stepNo])

  const forestRows =
    visibleState.status === "ready" && visibleState.data?.kind === "table"
      ? visibleState.data
      : null
  const forestStatus =
    visibleState.status === "loading" || visibleState.status === "idle"
      ? "loading"
      : forestRows
        ? "ready"
        : "missing"

  return (
    <Suspense fallback={<ArtifactLoadingState message="Loading chart" />}>
      <PoolingResult
        forestRows={forestRows}
        forestStatus={forestStatus}
        pooledRows={pooledRows}
      />
    </Suspense>
  )
}

function QueryArtifactEditor({
  data,
  onSaved,
  runId,
  stepNo,
}: {
  data: Record<string, unknown>
  onSaved: () => Promise<unknown>
  runId: string
  stepNo: number
}) {
  const terms = readTermLabels(data.terms)
  const warnings = readStringArray(data.warnings)
  const rationale = readString(data.rationale)
  const [queryDraft, setQueryDraft] = useState(readString(data.query))
  const [isSaving, setIsSaving] = useState(false)

  async function handleSaveQuery() {
    setIsSaving(true)
    try {
      await saveEditedStep(runId, stepNo, {
        data: {
          ...data,
          query: queryDraft,
        },
      })
      toast.success("Saved query edits")
      await onSaved()
    } catch (error) {
      toast.error(`Failed to save query edits: ${getErrorMessage(error)}`)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <label className="text-xs font-medium" htmlFor="query-artifact">
          Query
        </label>
        <Textarea
          className="min-h-32 font-mono text-xs"
          id="query-artifact"
          onChange={(event) => setQueryDraft(event.target.value)}
          value={queryDraft}
        />
      </div>
      <div className="flex justify-end">
        <Button
          disabled={isSaving}
          onClick={() => {
            void handleSaveQuery()
          }}
        >
          <SaveIcon />
          {isSaving ? "Saving..." : "Save edits"}
        </Button>
      </div>
      <MetadataList
        emptyLabel="No terms reported."
        items={terms}
        title="Terms"
      />
      {rationale ? (
        <div className="rounded-lg border bg-muted/20 p-3">
          <div className="text-xs font-medium">Rationale</div>
          <p className="mt-1 text-sm text-muted-foreground">{rationale}</p>
        </div>
      ) : null}
      <MetadataList
        emptyLabel="No warnings."
        items={warnings}
        title="Warnings"
        tone="warning"
      />
    </div>
  )
}

function EditableCsvArtifact({
  columns,
  onSaved,
  rows,
  runId,
  stepNo,
}: {
  columns: string[]
  onSaved: () => Promise<unknown>
  rows: Record<string, string>[]
  runId: string
  stepNo: number
}) {
  const [draftRows, setDraftRows] = useState<Record<string, string>[]>(() =>
    normalizeTableRows(rows, columns)
  )
  const [isSaving, setIsSaving] = useState(false)

  async function handleSaveRows() {
    setIsSaving(true)
    try {
      await saveEditedStep(runId, stepNo, {
        columns,
        rows: draftRows,
      })
      toast.success(`Saved step ${stepNo} edits`)
      await onSaved()
    } catch (error) {
      toast.error(`Failed to save edits: ${getErrorMessage(error)}`)
    } finally {
      setIsSaving(false)
    }
  }

  if (columns.length === 0) {
    return (
      <EmptyArtifactState
        icon={<TableIcon className="size-5" />}
        message="CSV artifact is empty."
      />
    )
  }

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-2 rounded-lg border border-border/70 bg-muted/15 px-2 py-2 sm:px-3 sm:py-2.5">
        <div className="flex min-w-0 items-baseline gap-2 sm:block">
          <div className="min-w-0 truncate text-sm font-medium">
            Editable table
          </div>
          <div className="shrink-0 text-xs text-muted-foreground sm:hidden">
            {draftRows.length} rows
          </div>
          <div className="mt-0.5 hidden text-xs text-muted-foreground sm:block">
            Loaded {draftRows.length} rows. Edits are saved as a step-level
            artifact override.
          </div>
        </div>
        <Button
          aria-label={isSaving ? "Saving edits" : "Save edits"}
          className="h-8 w-8 shrink-0 px-0 sm:w-auto sm:px-2.5"
          disabled={isSaving}
          onClick={() => {
            void handleSaveRows()
          }}
          size="sm"
        >
          <SaveIcon />
          <span className="sr-only sm:not-sr-only">
            {isSaving ? "Saving..." : "Save edits"}
          </span>
        </Button>
      </div>
      <div className="order-2">
        <TableSummaryPanel columns={columns} rows={draftRows} />
      </div>
      <div className="order-3">
        <EditableTable
          columns={columns}
          onChange={setDraftRows}
          rows={draftRows}
        />
      </div>
    </div>
  )
}

function MetadataList({
  emptyLabel,
  items,
  title,
  tone = "default",
}: {
  emptyLabel: string
  items: string[]
  title: string
  tone?: "default" | "warning"
}) {
  return (
    <div className="rounded-lg border bg-muted/20 p-3">
      <div className="text-xs font-medium">{title}</div>
      {items.length === 0 ? (
        <p className="mt-1 text-sm text-muted-foreground">{emptyLabel}</p>
      ) : (
        <div className="mt-2 flex flex-wrap gap-2">
          {items.map((item, index) => (
            <Badge
              className={cn(
                "max-w-full border",
                tone === "warning" &&
                  "border-amber-500/30 text-amber-700 dark:text-amber-300"
              )}
              key={`${item}-${index}`}
              variant="outline"
            >
              <span className="truncate">{item}</span>
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}

type MiniBarItem = {
  count?: number
  label: string
  tone?: "danger" | "success" | "warning"
  valueLabel: string
  percent: number
}

type PrimaryDistribution = {
  items: MiniBarItem[]
  title: string
  variant?: "screening"
}

function TableSummaryPanel({
  columns,
  rows,
  totalRows = rows.length,
}: {
  columns: string[]
  rows: Record<string, string>[]
  totalRows?: number
}) {
  if (columns.length === 0) {
    return null
  }

  const nonEmptyCells = rows.reduce(
    (total, row) =>
      total +
      columns.reduce(
        (columnTotal, column) =>
          columnTotal + (readCellValue(row[column]).trim() ? 1 : 0),
        0
      ),
    0
  )
  const totalCells = rows.length * columns.length
  const cellFillRate = totalCells > 0 ? nonEmptyCells / totalCells : 0
  const populatedFields = columns.filter((column) =>
    rows.some((row) => readCellValue(row[column]).trim())
  ).length
  const yearColumn = findColumn(columns, [
    "publicationyear",
    "pubyear",
    "year",
    "publicationdate",
  ])
  const yearValues = yearColumn
    ? rows
        .map((row) => parseYearValue(row[yearColumn]))
        .filter((year): year is number => year !== null)
    : []
  const yearRange =
    yearValues.length > 0
      ? `${Math.min(...yearValues)}-${Math.max(...yearValues)}`
      : "-"
  const completenessItems = buildCompletenessItems(columns, rows)
  const distribution = buildPrimaryDistribution(columns, rows)
  const summaryStats = [
    { label: "Rows", value: formatCompactNumber(totalRows) },
    { label: "Fields", value: String(columns.length) },
    { label: "Cell fill", value: formatPercent(cellFillRate) },
    { label: "Years", value: yearRange },
  ]

  return (
    <div className="min-w-0 rounded-lg border border-border/80 bg-card shadow-xs">
      <div className="space-y-3 p-3">
        <div className="flex min-w-0 items-center gap-2 text-sm font-medium">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
            <BarChart3Icon className="size-3.5" />
          </span>
          <div className="min-w-0">
            <div>Data snapshot</div>
            <div className="mt-0.5 hidden text-xs font-normal leading-4 text-muted-foreground sm:block">
              Coverage and distribution for the current artifact.
            </div>
          </div>
        </div>
        <div className="grid min-w-0 grid-cols-2 overflow-hidden rounded-lg border border-border/70 bg-muted/10 sm:grid-cols-4">
          {summaryStats.map((stat) => (
            <div
              className="min-w-0 border-b border-r border-border/60 px-2.5 py-2 last:border-r-0 even:border-r-0 sm:border-b-0 sm:even:border-r sm:last:border-r-0"
              key={stat.label}
            >
              <div className="truncate text-[0.62rem] font-medium uppercase text-muted-foreground sm:text-[0.68rem]">
                {stat.label}
              </div>
              <div className="mt-0.5 truncate font-mono text-sm font-semibold text-foreground">
                {stat.value}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="space-y-3 border-t border-border/70 p-3 sm:space-y-4">
        {distribution?.variant === "screening" ? (
          <ScreeningDecisionSummary
            items={distribution.items}
            title={distribution.title}
          />
        ) : distribution ? (
          <MiniBarList items={distribution.items} title={distribution.title} />
        ) : null}
        <MiniBarList
          items={completenessItems}
          title={`Coverage (${populatedFields}/${columns.length} fields)`}
        />
      </div>
    </div>
  )
}

function MiniBarList({
  items,
  title,
}: {
  items: MiniBarItem[]
  title: string
}) {
  if (items.length === 0) {
    return null
  }

  return (
    <div className="min-w-0 space-y-2">
      <div className="text-[0.68rem] font-medium uppercase text-muted-foreground">
        {title}
      </div>
      <div className="space-y-1">
        {items.map((item) => (
          <div className="min-w-0" key={item.label}>
            <div className="mb-0.5 flex items-center gap-2 text-xs">
              <span className="min-w-0 flex-1 truncate text-foreground/80">
                {formatStatLabel(item.label)}
              </span>
              <span className="shrink-0 text-muted-foreground">
                {item.valueLabel}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full rounded-full bg-primary/50",
                  item.tone === "danger" && "bg-rose-500/55",
                  item.tone === "success" && "bg-primary/65",
                  item.tone === "warning" && "bg-amber-500/60"
                )}
                style={{ width: `${Math.max(0, Math.min(item.percent, 100))}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ScreeningDecisionSummary({
  items,
  title,
}: {
  items: MiniBarItem[]
  title: string
}) {
  const total = items.reduce((sum, item) => sum + (item.count ?? 0), 0)
  const nonEmptyItems = items.filter((item) => (item.count ?? 0) > 0)
  const segmentedItems = nonEmptyItems.length > 0 ? nonEmptyItems : items

  return (
    <div className="min-w-0 space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[0.68rem] font-medium uppercase text-muted-foreground">
          {title}
        </div>
        <div className="text-xs text-muted-foreground">{total} total</div>
      </div>
      <div className="flex h-2 overflow-hidden rounded-full bg-border/60">
        {segmentedItems.map((item) => (
          <span
            aria-hidden="true"
            className={cn("min-w-1", getToneBarClass(item.tone))}
            key={item.label}
            style={{
              width:
                total > 0
                  ? `${Math.max(0, Math.min(item.percent, 100))}%`
                  : `${100 / Math.max(segmentedItems.length, 1)}%`,
            }}
          />
        ))}
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(6.5rem,1fr))] gap-2">
        {items.map((item) => (
          <div
            className={cn(
              "min-w-0 rounded-lg border bg-background px-2.5 py-2 shadow-xs",
              item.tone === "danger" && "border-rose-500/20",
              item.tone === "warning" && "border-amber-500/25",
              item.tone === "success" && "border-primary/25"
            )}
            key={item.label}
          >
            <div className="flex min-w-0 items-center gap-1.5">
              <span
                className={cn(
                  "size-2 shrink-0 rounded-full",
                  getToneBarClass(item.tone)
                )}
              />
              <span className="truncate text-xs font-medium">{item.label}</span>
            </div>
            <span className="mt-1.5 block font-mono text-lg font-semibold leading-none">
              {item.count ?? 0}
            </span>
            <span className="mt-0.5 block truncate text-[0.65rem] leading-4 text-muted-foreground">
              {formatPercent((item.count ?? 0) / Math.max(total, 1))}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function buildCompletenessItems(
  columns: string[],
  rows: Record<string, string>[]
): MiniBarItem[] {
  return columns
    .map((column) => {
      const filled = rows.filter((row) =>
        readCellValue(row[column]).trim()
      ).length
      const fillRate = rows.length > 0 ? filled / rows.length : 0

      return {
        label: column,
        valueLabel: `${filled}/${rows.length}`,
        percent: fillRate * 100,
      }
    })
    .sort(
      (first, second) =>
        first.percent - second.percent ||
        formatStatLabel(first.label).localeCompare(formatStatLabel(second.label))
    )
    .slice(0, 4)
}

function buildPrimaryDistribution(
  columns: string[],
  rows: Record<string, string>[]
): PrimaryDistribution | null {
  const screeningColumn = findColumn(columns, [
    "llmdecision",
    "llmlabel",
    "llmscreeningdecision",
    "llmsuggest",
    "llmsuggestion",
    "relevance",
    "relevancelevel",
    "screendecision",
    "screening",
    "screeningclass",
    "screeningdecision",
    "screeninglabel",
    "screeningresult",
    "decision",
    "eligibility",
    "include",
    "included",
  ])
  if (screeningColumn) {
    return {
      title: "Screening decisions",
      items: buildScreeningDecisionItems(rows, screeningColumn),
      variant: "screening",
    }
  }

  const column =
    findColumn(columns, [
      "status",
      "label",
      "outcome",
    ]) ?? findLowCardinalityColumn(columns, rows)

  if (column) {
    return {
      title: `Top ${formatStatLabel(column)}`,
      items: buildDistributionItems(
        rows.map((row) => readCellValue(row[column]).trim() || "(blank)")
      ),
    }
  }

  const yearColumn = findColumn(columns, [
    "publicationyear",
    "pubyear",
    "year",
    "publicationdate",
  ])
  if (!yearColumn) {
    return null
  }

  const yearItems = buildDistributionItems(
    rows
      .map((row) => parseYearValue(row[yearColumn]))
      .filter((year): year is number => year !== null)
      .map(String)
  )

  return yearItems.length > 0
    ? { title: `Top ${formatStatLabel(yearColumn)}`, items: yearItems }
    : null
}

function buildScreeningDecisionItems(
  rows: Record<string, string>[],
  column: string
): MiniBarItem[] {
  const counts = {
    unlikely: 0,
    possible: 0,
    strong: 0,
    unclassified: 0,
  }

  rows.forEach((row) => {
    const decision = classifyScreeningValue(row[column])
    counts[decision] += 1
  })

  const total = Math.max(rows.length, 1)
  const entries: Array<{
    count: number
    label: string
    tone?: MiniBarItem["tone"]
  }> = [
    {
      count: counts.unlikely,
      label: "Unlikely",
      tone: "danger" as const,
    },
    {
      count: counts.possible,
      label: "Possible",
      tone: "warning" as const,
    },
    {
      count: counts.strong,
      label: "Strong",
      tone: "success" as const,
    },
  ]
  if (counts.unclassified > 0) {
    entries.push({
      count: counts.unclassified,
      label: "Unclassified",
      tone: undefined,
    })
  }
  return entries.map((entry) => ({
    count: entry.count,
    label: entry.label,
    percent: (entry.count / total) * 100,
    tone: entry.tone,
    valueLabel: `${entry.count} (${formatPercent(entry.count / total)})`,
  }))
}

function getToneBarClass(tone?: MiniBarItem["tone"]) {
  if (tone === "danger") {
    return "bg-rose-500/55"
  }
  if (tone === "warning") {
    return "bg-amber-500/65"
  }
  if (tone === "success") {
    return "bg-primary/65"
  }

  return "bg-muted-foreground/45"
}

function classifyScreeningValue(value: unknown) {
  const normalized = normalizeColumnName(readCellValue(value))

  if (
    normalized === "u" ||
    normalized.includes("unlikely") ||
    normalized.includes("exclude") ||
    normalized === "no" ||
    normalized === "notcandidate"
  ) {
    return "unlikely"
  }
  if (
    normalized === "p" ||
    normalized.includes("possible") ||
    normalized.includes("maybe") ||
    normalized.includes("needsfulltext")
  ) {
    return "possible"
  }
  if (
    normalized === "s" ||
    normalized.includes("strong") ||
    normalized.includes("include") ||
    normalized === "yes"
  ) {
    return "strong"
  }

  return "unclassified"
}

function buildDistributionItems(values: string[]): MiniBarItem[] {
  const counts = new Map<string, number>()
  values.forEach((value) => {
    counts.set(value, (counts.get(value) ?? 0) + 1)
  })
  const entries = [...counts.entries()]
    .sort((first, second) => second[1] - first[1] || first[0].localeCompare(second[0]))
    .slice(0, 5)
  const maxCount = Math.max(...entries.map(([, count]) => count), 0)
  const total = values.length

  return entries.map(([label, count]) => ({
    label,
    valueLabel: `${count} (${formatPercent(total > 0 ? count / total : 0)})`,
    percent: maxCount > 0 ? (count / maxCount) * 100 : 0,
  }))
}

function findLowCardinalityColumn(
  columns: string[],
  rows: Record<string, string>[]
) {
  const blockedColumns = new Set([
    "abstract",
    "authors",
    "citation",
    "createdate",
    "doi",
    "journalbook",
    "keywords",
    "nihmsid",
    "pmcid",
    "pmid",
    "title",
  ])

  return columns.find((column) => {
    if (blockedColumns.has(normalizeColumnName(column))) {
      return false
    }
    const values = rows
      .map((row) => readCellValue(row[column]).trim())
      .filter(Boolean)
    const uniqueValues = new Set(values)

    return uniqueValues.size >= 2 && uniqueValues.size <= 8
  })
}

function findColumn(columns: string[], candidates: string[]) {
  const candidateSet = new Set(candidates)
  return columns.find((column) => candidateSet.has(normalizeColumnName(column)))
}

function normalizeColumnName(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "")
}

function parseYearValue(value: unknown) {
  const match = readCellValue(value).match(/\b(19|20)\d{2}\b/)

  return match ? Number(match[0]) : null
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`
}

function formatCompactNumber(value: number) {
  return Intl.NumberFormat(undefined, { notation: "compact" }).format(value)
}

function toRecordRow(headers: string[], row: string[]) {
  const record: Record<string, string> = {}
  headers.forEach((header, index) => {
    record[header || `Column ${index + 1}`] = row[index] ?? ""
  })

  return record
}

function CsvTablePreview({ text }: { text: string }) {
  const rows = parseCsv(text)
  const headers = rows[0] ?? []
  const tableRows = rows.slice(1).map((row) => toRecordRow(headers, row))
  const totalRows = Math.max(rows.length - 1, 0)

  if (headers.length === 0) {
    return (
      <EmptyArtifactState
        icon={<TableIcon className="size-5" />}
        message="CSV artifact is empty."
      />
    )
  }

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="rounded-lg border border-border/70 bg-muted/15 px-3 py-2.5">
        <div className="text-sm font-medium">CSV preview</div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          Search and inspect rows without leaving the pipeline page.
        </div>
      </div>
      <div className="order-2">
        <TableSummaryPanel
          columns={headers}
          rows={tableRows}
          totalRows={totalRows}
        />
      </div>
      <div className="order-3">
        <ReadonlyTablePreview
          columns={headers}
          rows={tableRows}
          searchPlaceholder="Search CSV rows"
          totalRows={totalRows}
        />
      </div>
    </div>
  )
}

function PooledCsvPreview({ text }: { text: string }) {
  const rows = parseCsv(text)
  const headers = rows[0] ?? []
  const pooledRow = rows[1] ?? []
  const stats = headers.map((header, index) => ({
    label: header || `Column ${index + 1}`,
    value: pooledRow[index] ?? "",
  }))

  if (stats.length === 0) {
    return (
      <EmptyArtifactState
        icon={<TableIcon className="size-5" />}
        message="Pooled CSV artifact is empty."
      />
    )
  }

  return (
    <div className="space-y-2">
      {stats.map((stat) => (
        <div className="rounded-lg border bg-muted/20 p-3" key={stat.label}>
          <div className="text-xs text-muted-foreground">
            {formatStatLabel(stat.label)}
          </div>
          <div className="mt-1 break-words font-mono text-sm">
            {stat.value || "-"}
          </div>
        </div>
      ))}
    </div>
  )
}

function ReadonlyTablePreview({
  columns,
  rows,
  maxRows = 200,
  searchPlaceholder = "Search rows",
  totalRows = rows.length,
}: {
  columns: string[]
  rows: Record<string, string>[]
  maxRows?: number
  searchPlaceholder?: string
  totalRows?: number
}) {
  const [query, setQuery] = useState("")
  const normalizedQuery = query.trim().toLowerCase()
  const indexedRows = useMemo(
    () => rows.map((row, sourceIndex) => ({ sourceIndex, values: row })),
    [rows]
  )
  const filteredRows = useMemo(() => {
    if (!normalizedQuery) {
      return indexedRows
    }

    return indexedRows.filter((row) =>
      columns.some((column) =>
        readCellValue(row.values[column]).toLowerCase().includes(normalizedQuery)
      )
    )
  }, [columns, indexedRows, normalizedQuery])
  const visibleRows = filteredRows.slice(0, maxRows)
  const tableShapeKey = `${columns.join("\u0000")}:${visibleRows.length}`
  const { canScrollRight, ref: tableScrollRef } =
    useHorizontalScrollHints(tableShapeKey)

  return (
    <div className="w-full min-w-0 max-w-full space-y-2">
      <div className="flex flex-col items-stretch gap-2 rounded-lg border border-border/70 bg-muted/15 px-2 py-2 sm:flex-row sm:items-center sm:px-3 sm:py-2.5">
        <div className="min-w-0 shrink-0 text-[0.7rem] leading-4 text-muted-foreground sm:text-xs">
          <span className="sm:hidden">
            <span className="font-medium text-foreground">
              {visibleRows.length}
            </span>
            /{filteredRows.length}
            <span className="mx-1 text-border">/</span>
            {totalRows} rows
          </span>
          <span className="hidden sm:inline">
            <span className="font-medium text-foreground">
              {visibleRows.length}
            </span>{" "}
            shown
            <span className="mx-1 text-border">/</span>
            {filteredRows.length} matched
            <span className="mx-1 text-border">/</span>
            {totalRows} rows
          </span>
        </div>
        <div className="relative min-w-0 w-full sm:w-80 sm:flex-none">
          <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search artifact rows"
            className="h-8 bg-background pl-8 pr-8 text-sm"
            onChange={(event) => setQuery(event.target.value)}
            onInput={(event) => setQuery(event.currentTarget.value)}
            placeholder={searchPlaceholder}
            value={query}
          />
          {query ? (
            <Button
              aria-label="Clear artifact search"
              className="absolute right-0.5 top-0.5"
              onClick={() => setQuery("")}
              size="icon-sm"
              type="button"
              variant="ghost"
            >
              <XIcon />
            </Button>
          ) : null}
        </div>
      </div>
      <div className="relative w-full min-w-0 max-w-full">
        <div
          className="max-h-[min(46vh,420px)] w-full min-w-0 max-w-full overflow-auto overscroll-contain rounded-lg border border-border/80 bg-card shadow-xs sm:max-h-[min(60vh,560px)]"
          ref={tableScrollRef}
        >
          <Table className="w-max min-w-full" unwrapped>
            <TableHeader className="bg-muted/95" sticky>
              <TableRow>
                <TableHead className="sticky left-0 z-50! w-12 min-w-12 max-w-12 bg-muted text-center shadow-[1px_0_0_var(--border)]">
                  #
                </TableHead>
                {columns.map((column, index) => (
                  <TableHead
                    className={cn(
                      "min-w-36 max-w-72 whitespace-normal align-top",
                      index === 0 &&
                        "sticky left-12 z-40! bg-muted shadow-[1px_0_0_var(--border)]"
                    )}
                    key={`${column}-${index}`}
                  >
                    {formatStatLabel(column || `Column ${index + 1}`)}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleRows.length > 0 ? (
                visibleRows.map((row) => (
                  <TableRow key={row.sourceIndex}>
                    <TableCell
                      className="sticky left-0 z-30 w-12 min-w-12 max-w-12 bg-card px-2 text-center font-mono text-xs text-muted-foreground shadow-[1px_0_0_var(--border)]"
                      title={`Row ${row.sourceIndex + 1}`}
                    >
                      {row.sourceIndex + 1}
                    </TableCell>
                    {columns.map((column, columnIndex) => {
                      const value = readCellValue(row.values[column])

                      return (
                        <TableCell
                          className={cn(
                            "max-w-80 truncate align-top",
                            columnIndex === 0 &&
                              "sticky left-12 z-20 bg-card shadow-[1px_0_0_var(--border)]"
                          )}
                          key={`${row.sourceIndex}-${column}-${columnIndex}`}
                          title={value}
                        >
                          {value}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell
                    className="h-24 text-center text-sm text-muted-foreground"
                    colSpan={(columns.length || 1) + 1}
                  >
                    {query ? "No matching rows." : "No rows."}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        {canScrollRight ? (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute bottom-px right-px top-px z-50 w-8 rounded-r-lg bg-gradient-to-l from-card via-card/85 to-transparent"
          />
        ) : null}
      </div>
    </div>
  )
}

function useHorizontalScrollHints(dependencyKey: string) {
  const ref = useRef<HTMLDivElement>(null)
  const [canScrollRight, setCanScrollRight] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node) {
      return
    }

    const update = () => {
      const maxScrollLeft = node.scrollWidth - node.clientWidth
      setCanScrollRight(node.scrollLeft < maxScrollLeft - 1)
    }

    update()
    const resizeObserver = new ResizeObserver(update)
    resizeObserver.observe(node)
    node.addEventListener("scroll", update, { passive: true })
    window.addEventListener("resize", update)

    return () => {
      resizeObserver.disconnect()
      node.removeEventListener("scroll", update)
      window.removeEventListener("resize", update)
    }
  }, [dependencyKey])

  return { canScrollRight, ref }
}

function JsonTextPreview({ text }: { text: string }) {
  const parsed = parseJsonRecord(text)
  const formatted = parsed ? JSON.stringify(parsed, null, 2) : text

  return <PlainTextPreview text={formatted} />
}

function PlainTextPreview({ text }: { text: string }) {
  return (
    <pre className="max-h-[420px] max-w-full overflow-auto rounded-lg border bg-muted/20 p-3 text-xs leading-relaxed">
      {text}
    </pre>
  )
}

function EmptyArtifactState({
  icon,
  message,
}: {
  icon: ReactNode
  message: string
}) {
  return (
    <div className="flex min-h-[280px] items-center justify-center rounded-lg border border-dashed bg-muted/30 p-6 text-center">
      <div className="flex max-w-sm flex-col items-center gap-2 text-sm text-muted-foreground">
        {icon}
        <p>{message}</p>
      </div>
    </div>
  )
}

function ArtifactLoadingState({ message }: { message: string }) {
  return (
    <div
      aria-busy="true"
      className="min-h-[280px] rounded-lg border border-dashed bg-muted/25 p-4"
    >
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <LoaderCircleIcon className="size-4 motion-safe:animate-spin motion-reduce:animate-none" />
        <span>{message}</span>
      </div>
      <div className="mt-5 space-y-3">
        <Skeleton className="h-4 w-2/5" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-11/12" />
        <Skeleton className="h-8 w-4/5" />
      </div>
    </div>
  )
}

function eventIndicatesStepRefresh(event: RunEvent) {
  const level = event.level.toLowerCase()
  const message = event.message.toLowerCase()

  return (
    event.step_no !== null &&
    (level === "error" ||
      ["complete", "completed", "done", "failed", "finished", "success"].some(
        (token) => message.includes(token)
      ))
  )
}

function mergeRunEvents(currentEvents: RunEvent[], nextEvents: RunEvent[]) {
  const eventsById = new Map<number, RunEvent>()

  currentEvents.forEach((event) => {
    eventsById.set(event.id, event)
  })
  nextEvents.forEach((event) => {
    eventsById.set(event.id, event)
  })

  return [...eventsById.values()]
    .sort((first, second) => first.id - second.id)
    .slice(-500)
}

function resolveRunDetailTab(value: string | null): RunDetailTab {
  return RUN_DETAIL_TABS.includes(value as RunDetailTab)
    ? (value as RunDetailTab)
    : "output"
}

function getDefaultPipelineStepId(steps: StepRead[] = []): PipelineStepId {
  const statusByBackendStep = new Map<number, ReturnType<typeof normalizeStatus>>()
  for (const step of steps) {
    statusByBackendStep.set(step.step_no, normalizeStatus(step.status))
  }

  const runningStep = PIPELINE_STEPS.find(
    (step) => statusByBackendStep.get(step.backendStep) === "running"
  )
  if (runningStep) {
    return runningStep.id
  }

  const errorStep = PIPELINE_STEPS.find(
    (step) => statusByBackendStep.get(step.backendStep) === "error"
  )
  if (errorStep) {
    return errorStep.id
  }

  const latestDoneStep = [...PIPELINE_STEPS]
    .reverse()
    .find((step) => statusByBackendStep.get(step.backendStep) === "done")

  return latestDoneStep?.id ?? PIPELINE_STEPS[0].id
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ""
  let inQuotes = false

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]
    const nextChar = text[index + 1]

    if (char === '"') {
      if (inQuotes && nextChar === '"') {
        field += '"'
        index += 1
      } else {
        inQuotes = !inQuotes
      }
      continue
    }

    if (char === "," && !inQuotes) {
      row.push(field)
      field = ""
      continue
    }

    if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && nextChar === "\n") {
        index += 1
      }
      row.push(field)
      if (row.some((cell) => cell.trim())) {
        rows.push(row)
      }
      row = []
      field = ""
      continue
    }

    field += char
  }

  row.push(field)
  if (row.some((cell) => cell.trim())) {
    rows.push(row)
  }

  return rows
}

function parseJsonRecord(text: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(text) as unknown
    return isRecord(parsed) ? parsed : null
  } catch {
    return null
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function readString(value: unknown) {
  return typeof value === "string" ? value : ""
}

function getDisplayParamEntries(params: Record<string, unknown>) {
  return Object.entries(params)
    .filter(([, value]) => isDisplayParamValue(value))
    .map(([key, value]) => ({
      key,
      value: formatParamValue(value),
    }))
    .sort((first, second) => first.key.localeCompare(second.key))
}

function isDisplayParamValue(value: unknown) {
  if (value === null || value === undefined) {
    return false
  }
  if (typeof value === "string") {
    return value.trim().length > 0
  }
  if (Array.isArray(value)) {
    return value.length > 0
  }
  if (typeof value === "object") {
    return Object.keys(value).length > 0
  }

  return true
}

function formatParamValue(value: unknown): string {
  if (typeof value === "string") {
    return value
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value)
  }
  if (Array.isArray(value)) {
    return value.map((item) => formatParamValue(item)).join(", ")
  }
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value)
  }

  return String(value ?? "")
}

function readStringArray(value: unknown) {
  if (!Array.isArray(value)) {
    return []
  }

  return value
    .map((item) => (typeof item === "string" ? item : null))
    .filter((item): item is string => Boolean(item))
}

function readTermLabels(value: unknown) {
  if (!Array.isArray(value)) {
    return []
  }

  return value
    .map((item) => {
      if (typeof item === "string") {
        return item
      }
      if (!isRecord(item)) {
        return null
      }
      const concept = readString(item.concept)
      const synonyms = readStringArray(item.synonyms)
      if (!concept && synonyms.length === 0) {
        return null
      }
      return synonyms.length > 0
        ? `${concept || "Term"}: ${synonyms.join(", ")}`
        : concept
    })
    .filter((item): item is string => Boolean(item))
}

function normalizeTableRows(
  rows: Record<string, string>[],
  columns: string[]
): Record<string, string>[] {
  return rows.map((row) => {
    const normalized: Record<string, string> = {}
    columns.forEach((column) => {
      normalized[column] = readCellValue(row[column])
    })
    return normalized
  })
}

function readCellValue(value: unknown) {
  return typeof value === "string" ? value : String(value ?? "")
}

function summarizeRunParams(params: Record<string, unknown>) {
  const values = [
    readString(params.disease),
    readString(params.parameter),
    readString(params.keywords),
  ].filter(Boolean)

  return values.length > 0 ? values.join(" / ") : "No run params"
}

function formatStepTiming(step: StepRead | undefined) {
  if (!step) {
    return "Step record not created yet."
  }

  if (step.started_at && step.finished_at) {
    return `${formatDateTime(step.started_at)} -> ${formatDateTime(
      step.finished_at
    )}`
  }

  if (step.started_at) {
    return `Started ${formatDateTime(step.started_at)}`
  }

  return "Not started"
}

function formatDateTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return date.toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function formatEventTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
}

function formatEventCount(count: number) {
  return `${count} ${count === 1 ? "event" : "events"}`
}

function getEventLevelStyle(level: string) {
  const normalized = level.toLowerCase()

  if (normalized === "error") {
    return {
      badgeClassName: "border-destructive/30 text-destructive",
      dotClassName: "bg-destructive",
      label: "error",
    }
  }

  if (normalized === "warn" || normalized === "warning") {
    return {
      badgeClassName: "border-amber-500/30 text-amber-700 dark:text-amber-300",
      dotClassName: "bg-amber-500",
      label: "warn",
    }
  }

  return {
    badgeClassName: "border-border text-muted-foreground",
    dotClassName: "bg-muted-foreground/55",
    label: "info",
  }
}

function formatStatLabel(value: string) {
  return value.replaceAll("_", " ")
}
