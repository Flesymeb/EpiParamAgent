import { useEffect, useMemo, useRef, useState } from "react"
import { CheckIcon, XIcon } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { motion, useReducedMotion } from "motion/react"

import { Button } from "@/components/ui/button"
import { PIPELINE_STEPS } from "@/lib/pipeline"
import type { PipelineStepId } from "@/lib/pipeline"
import { normalizeStatus } from "@/lib/status"
import type { NormalizedStatus } from "@/lib/status"
import { cn } from "@/lib/utils"

type PipelineStepperProps = {
  currentStepId: PipelineStepId
  editedStepNos?: ReadonlySet<number>
  onStepChange: (stepId: PipelineStepId) => void
  stepStatuses?: Partial<Record<number, string>>
}

type StepperSnapshot = {
  currentStepId: PipelineStepId
  statuses: Partial<Record<number, NormalizedStatus>>
}

type StepperMotionEvent = {
  sweepConnectorStepNo: number | null
  spinStepNo: number | null
  token: number
}

export function PipelineStepper({
  currentStepId,
  editedStepNos = new Set<number>(),
  onStepChange,
  stepStatuses = {},
}: PipelineStepperProps) {
  const shouldReduceMotion = useReducedMotion()
  const currentStepNumber =
    PIPELINE_STEPS.find((step) => step.id === currentStepId)?.number ??
    PIPELINE_STEPS[0].number
  const normalizedStatuses = useMemo(() => {
    const statuses: Partial<Record<number, NormalizedStatus>> = {}

    PIPELINE_STEPS.forEach((step) => {
      statuses[step.number] = normalizeStatus(stepStatuses[step.backendStep])
    })

    return statuses
  }, [stepStatuses])
  const previousSnapshotRef = useRef<StepperSnapshot | null>(null)
  const [motionEvent, setMotionEvent] = useState<StepperMotionEvent>({
    sweepConnectorStepNo: null,
    spinStepNo: null,
    token: 0,
  })

  useEffect(() => {
    const snapshot: StepperSnapshot = {
      currentStepId,
      statuses: normalizedStatuses,
    }
    const previousSnapshot = previousSnapshotRef.current
    previousSnapshotRef.current = snapshot

    if (!previousSnapshot) {
      return
    }

    let sweepConnectorStepNo: number | null = null
    let spinStepNo: number | null = null

    // Switching steps: spin the target ring and sweep a loading pulse along the
    // connector that leads INTO it.
    if (previousSnapshot.currentStepId !== currentStepId) {
      spinStepNo = currentStepNumber
      sweepConnectorStepNo = currentStepNumber
    }

    // A step finishing wins: spin it and sweep/fill the connector LEAVING it.
    PIPELINE_STEPS.forEach((step, index) => {
      const previousStatus = previousSnapshot.statuses[step.number]
      const nextStatus = normalizedStatuses[step.number]

      if (previousStatus !== "done" && nextStatus === "done") {
        spinStepNo = step.number
        sweepConnectorStepNo = PIPELINE_STEPS[index + 1]?.number ?? null
      }
    })

    if (sweepConnectorStepNo !== null || spinStepNo !== null) {
      setMotionEvent((event) => ({
        sweepConnectorStepNo,
        spinStepNo,
        token: event.token + 1,
      }))
    }
  }, [
    currentStepId,
    currentStepNumber,
    normalizedStatuses,
    shouldReduceMotion,
  ])

  useEffect(() => {
    if (motionEvent.token === 0) {
      return
    }

    const timeoutId = window.setTimeout(() => {
      setMotionEvent((event) =>
        event.token === motionEvent.token
          ? {
              sweepConnectorStepNo: null,
              spinStepNo: null,
              token: event.token,
            }
          : event
      )
    }, 900)

    return () => window.clearTimeout(timeoutId)
  }, [motionEvent.token, shouldReduceMotion])

  return (
    <nav aria-label="Pipeline steps" className="w-full overflow-x-auto px-2 pb-1 pt-2.5">
      <ol className="flex w-full items-start justify-center px-1 py-1">
        {PIPELINE_STEPS.map((step, index) => {
          const isActive = step.id === currentStepId
          const normalizedStatus =
            normalizedStatuses[step.number] ?? "pending"
          const isComplete = normalizedStatus === "done"
          const hasError = normalizedStatus === "error"
          const isRunning = normalizedStatus === "running"
          const isEdited = editedStepNos.has(step.backendStep)
          const previousStep = PIPELINE_STEPS[index - 1]
          const previousStatus = previousStep
            ? normalizedStatuses[previousStep.number]
            : "pending"
          const connectorFilled = previousStatus === "done"
          const connectorIsAnimating =
            motionEvent.sweepConnectorStepNo === step.number
          const stepIsAnimating = motionEvent.spinStepNo === step.number
          const buttonTintClass = cn(
            isActive && "bg-emerald-500/12 dark:bg-emerald-500/15",
            hasError && "bg-destructive/10",
            isRunning && "bg-sky-500/12"
          )

          return (
            <li
              className="relative flex w-24 flex-none flex-col items-center gap-1.5"
              key={step.id}
            >
              {index > 0 ? (
                <span
                  aria-hidden="true"
                  className="absolute left-[-28px] top-5 z-0 h-px w-[56px] overflow-hidden rounded-full bg-border"
                >
                  {/* permanent green fill once the previous step is done */}
                  <motion.span
                    className="absolute inset-y-0 left-0 rounded-full bg-emerald-500"
                    initial={
                      connectorIsAnimating && connectorFilled
                        ? { width: "0%" }
                        : false
                    }
                    animate={{ width: connectorFilled ? "100%" : "0%" }}
                    transition={{
                      duration:
                        connectorIsAnimating && connectorFilled ? 0.7 : 0.3,
                      ease: "easeOut",
                    }}
                    key={
                      connectorIsAnimating
                        ? `fill-${motionEvent.token}`
                        : `fill-${step.number}`
                    }
                  />
                  {/* transient loading sweep on switch / completion (kept visible
                      even under reduced-motion so stage feedback is never lost) */}
                  {connectorIsAnimating ? (
                    <motion.span
                      aria-hidden="true"
                      className={cn(
                        "absolute inset-y-0 w-6 rounded-full blur-[1px]",
                        connectorFilled
                          ? "bg-emerald-200/70 dark:bg-emerald-100/40"
                          : "bg-primary/55"
                      )}
                      initial={{ x: "-140%", opacity: 0 }}
                      animate={{ x: "260%", opacity: [0, 1, 0] }}
                      transition={{ duration: 0.7, ease: "easeOut" }}
                      key={`sweep-${motionEvent.token}`}
                    />
                  ) : null}
                  {/* continuous indeterminate flow while this stage is running */}
                  {isRunning ? (
                    <motion.span
                      aria-hidden="true"
                      className="absolute inset-y-0 w-5 rounded-full bg-sky-400/70 blur-[1px]"
                      initial={{ x: "-120%" }}
                      animate={{ x: "340%" }}
                      transition={{
                        duration: 1.1,
                        ease: "linear",
                        repeat: Infinity,
                      }}
                    />
                  ) : null}
                </span>
              ) : null}
              <Button
                aria-current={isActive ? "step" : undefined}
                aria-label={`${step.number}. ${step.label}`}
                className={cn(
                  "relative z-10 size-10 overflow-visible rounded-full border bg-card p-0 transition-[border-color,box-shadow,transform] duration-200 hover:shadow-sm motion-safe:hover:-translate-y-0.5 dark:bg-background",
                  "border-border text-muted-foreground hover:bg-muted/70 hover:text-foreground",
                  isActive &&
                    "border-emerald-500/55 text-emerald-700 shadow-sm shadow-emerald-500/15 dark:text-emerald-300",
                  isComplete &&
                    "border-emerald-500/35 text-emerald-700 dark:text-emerald-300",
                  hasError && "border-destructive/45 text-destructive",
                  isRunning &&
                    "border-sky-500/45 text-sky-700 dark:text-sky-300"
                )}
                onClick={() => onStepChange(step.id)}
                variant="outline"
              >
                <span
                  aria-hidden="true"
                  className="absolute inset-0 z-0 rounded-full bg-card dark:bg-background"
                />
                {buttonTintClass ? (
                  <span
                    aria-hidden="true"
                    className={cn(
                      "absolute inset-0 z-0 rounded-full",
                      buttonTintClass
                    )}
                  />
                ) : null}
                {stepIsAnimating ? (
                  <motion.span
                    aria-hidden="true"
                    className={cn(
                      "pointer-events-none absolute -inset-1 rounded-full border-2 border-emerald-500/25 border-t-emerald-500",
                      hasError &&
                        "border-destructive/20 border-t-destructive",
                      isRunning && "border-sky-500/20 border-t-sky-500"
                    )}
                    animate={{ opacity: 0, rotate: 360, scale: 1.12 }}
                    initial={{ opacity: 0.95, rotate: 0, scale: 1 }}
                    key={`spin-${motionEvent.token}-${step.number}`}
                    transition={{
                      duration: 0.72,
                      ease: [0.22, 1, 0.36, 1],
                    }}
                  />
                ) : null}
                {isActive ? (
                  <motion.span
                    aria-hidden="true"
                    className="absolute inset-0 rounded-full bg-emerald-500/[0.1] dark:bg-emerald-400/[0.12]"
                    layoutId="pipeline-step-active"
                    transition={
                      shouldReduceMotion
                        ? { duration: 0 }
                        : { type: "spring", stiffness: 420, damping: 36 }
                    }
                  />
                ) : null}
                <StepStatusMark icon={step.icon} status={normalizedStatus} />
                <span
                  aria-hidden="true"
                  className={cn(
                    "absolute -left-1.5 -top-1.5 z-30 flex size-4 items-center justify-center rounded-full border bg-background text-[0.6rem] font-semibold leading-none",
                    "border-border text-muted-foreground",
                    isActive &&
                      "border-emerald-500/45 text-emerald-700 dark:text-emerald-300",
                    isComplete && "border-emerald-600/60 text-emerald-700 dark:text-emerald-300",
                    hasError && "border-destructive/45 text-destructive",
                    isRunning && "border-sky-500/45 text-sky-700 dark:text-sky-300"
                  )}
                >
                  {step.number}
                </span>
                {isEdited ? (
                  <span
                    aria-label="Edited artifact"
                    className="absolute -right-0.5 -top-0.5 z-20 size-2.5 rounded-full border border-background bg-primary"
                    title="Edited"
                  />
                ) : null}
              </Button>
              <span
                className={cn(
                  "min-w-0 max-w-full truncate px-1 text-xs font-medium leading-5 text-muted-foreground transition-colors",
                  isActive && "text-emerald-700 dark:text-emerald-300",
                  isComplete && "text-foreground",
                  hasError && "text-destructive",
                  isRunning && "text-sky-700 dark:text-sky-300"
                )}
                title={step.title}
              >
                {step.label}
              </span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

function StepStatusMark({
  icon: Icon,
  status,
}: {
  icon: LucideIcon
  status: NormalizedStatus
}) {
  const isComplete = status === "done"
  const hasError = status === "error"
  const isRunning = status === "running"

  return (
    <span className="relative z-10 flex size-full items-center justify-center">
      {isRunning ? (
        <>
          <span
            aria-hidden="true"
            className="absolute -inset-1 rounded-full border border-sky-500/35 animate-pulse-ring"
          />
          <span
            aria-hidden="true"
            className="absolute -inset-0.5 rounded-full border-2 border-sky-500/70 border-t-transparent animate-spin"
          />
        </>
      ) : null}
      <Icon className="relative z-10 size-4" />
      {isComplete ? (
        <span className="absolute -bottom-0.5 -right-0.5 z-20 flex size-4 items-center justify-center rounded-full border border-background bg-emerald-500 text-white">
          <CheckIcon className="size-3" />
        </span>
      ) : null}
      {hasError ? (
        <span className="absolute -bottom-0.5 -right-0.5 z-20 flex size-4 items-center justify-center rounded-full border border-background bg-destructive text-destructive-foreground">
          <XIcon className="size-3" />
        </span>
      ) : null}
    </span>
  )
}
