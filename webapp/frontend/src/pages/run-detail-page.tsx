import type { ReactNode } from "react"
import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import {
  AlertCircleIcon,
  FileTextIcon,
  LoaderCircleIcon,
  PlayIcon,
  RefreshCwIcon,
  SaveIcon,
  TableIcon,
} from "lucide-react"
import { toast } from "sonner"

import {
  artifactUrl,
  getStepFile,
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
import { PipelineStepper } from "@/components/pipeline-stepper"
import { PoolingResult } from "@/components/pooling-result"
import { StatusBadge } from "@/components/status-badge"
import { StepConfigForm } from "@/components/step-config-form"
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
import { useRun } from "@/hooks/use-run"
import { getErrorMessage } from "@/lib/errors"
import {
  getPipelineStep,
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

export function RunDetailPage() {
  const { runId = "" } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const currentStepId = resolvePipelineStepId(searchParams.get("step"))
  const currentStep = getPipelineStep(currentStepId)
  // Capture/test aid: ?nosse=1 skips long-lived SSE so headless tools can settle.
  const shouldSkipEventSource =
    searchParams.get("nosse") === "1" ||
    (import.meta.env.DEV && searchParams.has("nosse"))
  const { detail, error, isLoading, refresh } = useRun(runId)
  const [startingStepNo, setStartingStepNo] = useState<number | null>(null)
  const [stepParams, setStepParams] = useState<Record<string, unknown>>({})
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

  const selectedStep = stepsByNumber.get(currentStep.number)
  const selectedStatus = normalizeStatus(selectedStep?.status)
  const selectedHasEditedArtifact = Boolean(selectedStep?.edited_artifact_path)
  const selectedArtifactPath =
    selectedStep?.edited_artifact_path ?? selectedStep?.artifact_path
  const events = eventState.runId === runId ? eventState.events : []
  const streamKey = `${runId}:${streamVersion}`
  const isStreamConnected = !shouldSkipEventSource && streamErrorKey !== streamKey
  const anyStepRunning =
    detail?.steps.some((step) => normalizeStatus(step.status) === "running") ??
    false
  const isSelectedStepRunning =
    selectedStatus === "running" || startingStepNo === currentStep.number

  useEffect(() => {
    if (error) {
      toast.error(`Failed to load run: ${error}`)
    }
  }, [error])

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

          return {
            runId,
            events: [...currentEvents, event].slice(-500),
          }
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

  function handleStepChange(nextStepId: PipelineStepId) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set("step", nextStepId)
      return next
    })
  }

  async function handleStartStep() {
    if (!runId) {
      return
    }

    setStartingStepNo(currentStep.number)
    setStreamVersion((current) => current + 1)

    try {
      await startStep(runId, currentStep.number, stepParams)
      await refresh()
    } catch (startError) {
      toast.error(
        `Failed to start step ${currentStep.number}: ${getErrorMessage(
          startError
        )}`
      )
    } finally {
      setStartingStepNo(null)
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
    return <RunDetailSkeleton runId={runId} />
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
    <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge title={runId} variant="secondary">
              Run {shortRunId(runId)}
            </Badge>
            {detail ? (
              <StatusBadge status={detail.run.status} />
            ) : null}
            {anyStepRunning ? (
              <StatusBadge label="step running" status="running" />
            ) : null}
          </div>
          <h1 className="mt-3 text-2xl font-semibold tracking-normal">
            Pipeline
          </h1>
          <p
            className="max-w-4xl truncate text-sm text-muted-foreground"
            title={detail ? summarizeRunParams(detail.run.params) : undefined}
          >
            {detail ? summarizeRunParams(detail.run.params) : "Loading run..."}
          </p>
        </div>
        <Button
          onClick={() => {
            void refresh().catch((refreshError) => {
              toast.error(`Failed to refresh run: ${getErrorMessage(refreshError)}`)
            })
          }}
          variant="outline"
        >
          <RefreshCwIcon />
          Refresh
        </Button>
      </div>

      <PipelineStepper
        currentStepId={currentStepId}
        editedStepNos={editedStepNos}
        onStepChange={handleStepChange}
        stepStatuses={stepStatuses}
      />

      <div className="grid flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <Card
          className={cn(
            "relative min-h-[520px] transition-[box-shadow] duration-300",
            isSelectedStepRunning && "shadow-sm shadow-sky-500/10"
          )}
        >
          {isSelectedStepRunning ? <RunningProgressBar /> : null}
          <CardHeader>
            <CardTitle>
              {currentStep.number}. {currentStep.label}
            </CardTitle>
            <CardDescription>{currentStep.description}</CardDescription>
            <CardAction className="flex flex-wrap justify-end gap-2">
              {selectedHasEditedArtifact ? (
                <Badge variant="secondary">edited</Badge>
              ) : null}
              <StatusBadge status={selectedStep?.status} />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            <StepConfigForm
              disabled={isSelectedStepRunning}
              initialValues={detail?.run.params ?? {}}
              key={currentStep.number}
              onChange={setStepParams}
              stepNumber={currentStep.number}
            />
            <div
              className={cn(
                "relative flex flex-col gap-3 overflow-hidden rounded-lg border bg-muted/20 p-3 transition-[background-color,border-color,box-shadow] duration-300 sm:flex-row sm:items-center sm:justify-between",
                isSelectedStepRunning &&
                  "border-sky-500/25 bg-sky-500/5 shadow-sm shadow-sky-500/10"
              )}
            >
              <div className="min-w-0">
                <div className="truncate font-medium" title={currentStep.title}>
                  {currentStep.title}
                </div>
                <div
                  className="truncate text-xs text-muted-foreground"
                  title={formatStepTiming(selectedStep)}
                >
                  {formatStepTiming(selectedStep)}
                </div>
              </div>
              <Button
                aria-busy={isSelectedStepRunning}
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
                  : `Run step ${currentStep.number}`}
              </Button>
            </div>

            <ArtifactPreview
              artifactPath={selectedArtifactPath}
              hasEditedArtifact={selectedHasEditedArtifact}
              onSaved={refresh}
              runId={runId}
              stepNo={currentStep.number}
              stepStatus={selectedStep?.status}
            />
          </CardContent>
        </Card>

        <EventsPanel events={events} isConnected={isStreamConnected} />
      </div>
    </div>
  )
}

function RunningProgressBar() {
  return (
    <div
      aria-hidden="true"
      className="absolute inset-x-0 top-0 h-0.5 overflow-hidden bg-sky-500/10"
    >
      <span className="block h-full w-1/3 bg-gradient-to-r from-transparent via-sky-500/70 to-transparent animate-shimmer" />
    </div>
  )
}

function RunDetailSkeleton({ runId }: { runId: string }) {
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0 flex-1 space-y-3">
          <Badge title={runId} variant="secondary">
            Run {shortRunId(runId)}
          </Badge>
          <Skeleton className="h-8 w-44" />
          <Skeleton className="h-4 max-w-2xl" />
        </div>
        <Skeleton className="h-8 w-24" />
      </div>
      <div className="grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-5">
        {PIPELINE_SKELETON_KEYS.map((key) => (
          <Skeleton className="h-24" key={key} />
        ))}
      </div>
      <div className="grid flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
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
        <Card className="min-h-[320px]">
          <CardHeader>
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-4 w-36" />
          </CardHeader>
          <CardContent className="space-y-3">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
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

const PIPELINE_SKELETON_KEYS = ["query", "retrieve", "screen", "code", "pool"]

function ArtifactPreview({
  artifactPath,
  hasEditedArtifact,
  onSaved,
  runId,
  stepNo,
  stepStatus,
}: {
  artifactPath: string | null | undefined
  hasEditedArtifact: boolean
  onSaved: () => Promise<unknown>
  runId: string
  stepNo: number
  stepStatus: string | null | undefined
}) {
  const normalizedStatus = normalizeStatus(stepStatus)

  if (normalizedStatus !== "done") {
    return (
      <EmptyArtifactState
        icon={<FileTextIcon className="size-5" />}
        message="Artifact preview appears after this step finishes."
      />
    )
  }

  if (!artifactPath) {
    return (
      <EmptyArtifactState
        icon={<FileTextIcon className="size-5" />}
        message="Step is done, but no artifact path was reported."
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
          throw new Error(`Artifact request failed with ${response.status}`)
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
        toast.error(`Failed to load artifact: ${message}`)
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
    <div className="space-y-3">
      <ArtifactPathLabel
        artifactPath={artifactPath}
        hasEditedArtifact={hasEditedArtifact}
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
          error: message,
        })
        toast.error(`Failed to load artifact rows: ${message}`)
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
    <div className="space-y-3">
      <ArtifactPathLabel
        artifactPath={artifactPath}
        hasEditedArtifact={hasEditedArtifact}
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

function ArtifactPathLabel({
  artifactPath,
  hasEditedArtifact,
}: {
  artifactPath: string
  hasEditedArtifact: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
      <FileTextIcon className="size-4 text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate" title={artifactPath}>
        {artifactPath}
      </span>
      <Badge variant={hasEditedArtifact ? "secondary" : "outline"}>
        {hasEditedArtifact ? "edited" : "original"}
      </Badge>
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
    <PoolingResult
      forestRows={forestRows}
      forestStatus={forestStatus}
      pooledRows={pooledRows}
    />
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
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-xs text-muted-foreground">
          Loaded {draftRows.length} rows for editing.
        </div>
        <Button
          disabled={isSaving}
          onClick={() => {
            void handleSaveRows()
          }}
        >
          <SaveIcon />
          {isSaving ? "Saving..." : "Save edits"}
        </Button>
      </div>
      <EditableTable
        columns={columns}
        onChange={setDraftRows}
        rows={draftRows}
      />
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

function CsvTablePreview({ text }: { text: string }) {
  const rows = parseCsv(text)
  const headers = rows[0] ?? []
  const bodyRows = rows.slice(1, 51)
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
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground">
        Showing {bodyRows.length} of {totalRows} rows.
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            {headers.map((header, index) => (
              <TableHead key={`${header}-${index}`}>
                {header || `Column ${index + 1}`}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {bodyRows.map((row, rowIndex) => (
            <TableRow key={rowIndex}>
              {headers.map((_, cellIndex) => (
                <TableCell
                  className="max-w-[18rem] truncate"
                  key={`${rowIndex}-${cellIndex}`}
                  title={row[cellIndex] ?? ""}
                >
                  {row[cellIndex] ?? ""}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
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
    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
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

function JsonTextPreview({ text }: { text: string }) {
  const parsed = parseJsonRecord(text)
  const formatted = parsed ? JSON.stringify(parsed, null, 2) : text

  return <PlainTextPreview text={formatted} />
}

function PlainTextPreview({ text }: { text: string }) {
  return (
    <pre className="max-h-[420px] overflow-auto rounded-lg border bg-muted/20 p-3 text-xs leading-relaxed">
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

function shortRunId(runId: string) {
  return runId.length > 12 ? `${runId.slice(0, 8)}...` : runId
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

function formatStatLabel(value: string) {
  return value.replaceAll("_", " ")
}
