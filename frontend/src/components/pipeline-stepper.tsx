import { CheckIcon, XIcon } from "lucide-react"
import { AnimatePresence, motion, useReducedMotion } from "motion/react"

import { StatusBadge } from "@/components/status-badge"
import { Badge } from "@/components/ui/badge"
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

export function PipelineStepper({
  currentStepId,
  editedStepNos = new Set<number>(),
  onStepChange,
  stepStatuses = {},
}: PipelineStepperProps) {
  const shouldReduceMotion = useReducedMotion()

  return (
    <nav aria-label="Pipeline steps" className="w-full overflow-x-auto pb-1">
      <ol className="grid min-w-[760px] grid-cols-5 gap-3">
        {PIPELINE_STEPS.map((step, index) => {
          const isActive = step.id === currentStepId
          const normalizedStatus = normalizeStatus(stepStatuses[step.number])
          const isComplete = normalizedStatus === "done"
          const hasError = normalizedStatus === "error"
          const isRunning = normalizedStatus === "running"
          const isEdited = editedStepNos.has(step.number)
          const previousStep = PIPELINE_STEPS[index - 1]
          const previousStatus = previousStep
            ? normalizeStatus(stepStatuses[previousStep.number])
            : "pending"
          const connectorFilled = previousStatus === "done"

          return (
            <li className="relative" key={step.id}>
              {index > 0 ? (
                <span
                  aria-hidden="true"
                  className="absolute -left-3 top-1/2 z-0 h-0.5 w-3 overflow-hidden rounded-full bg-border"
                >
                  <span
                    className={cn(
                      "block h-full rounded-full transition-[width,background-color] duration-500 ease-out",
                      connectorFilled
                        ? "w-full bg-emerald-500"
                        : "w-0 bg-muted-foreground/30"
                    )}
                  />
                </span>
              ) : null}
              <Button
                className={cn(
                  "relative h-auto min-h-24 w-full justify-start gap-3 overflow-hidden rounded-lg border px-3 py-3 text-left transition-[background-color,border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:shadow-sm",
                  isActive
                    ? "border-primary/45 bg-primary/5 text-foreground shadow-sm dark:bg-primary/10"
                    : "border-border bg-card text-card-foreground hover:bg-muted/60",
                  hasError &&
                    !isActive &&
                    "border-destructive/25 bg-destructive/5",
                  isRunning &&
                    !isActive &&
                    "border-sky-500/25 bg-sky-500/5"
                )}
                onClick={() => onStepChange(step.id)}
                variant="outline"
              >
                {isActive ? (
                  <motion.span
                    aria-hidden="true"
                    className="absolute inset-0 rounded-lg bg-primary/[0.06] dark:bg-primary/[0.10]"
                    layoutId="pipeline-step-active"
                    transition={
                      shouldReduceMotion
                        ? { duration: 0 }
                        : { type: "spring", stiffness: 420, damping: 36 }
                    }
                  />
                ) : null}
                <StepStatusMark
                  isActive={isActive}
                  shouldReduceMotion={Boolean(shouldReduceMotion)}
                  status={normalizedStatus}
                  stepNumber={step.number}
                />
                <span className="relative z-10 min-w-0 flex-1">
                  <span
                    className={cn(
                      "block truncate text-sm font-medium",
                      isComplete && "text-emerald-700 dark:text-emerald-300",
                      hasError && "text-destructive",
                      isRunning && "text-sky-700 dark:text-sky-300"
                    )}
                    title={`${step.number} ${step.label}`}
                  >
                    {step.number} {step.label}
                  </span>
                  <span
                    className="block truncate text-xs text-muted-foreground"
                    title={step.title}
                  >
                    {step.title}
                  </span>
                </span>
                <StatusBadge
                  className="relative z-10 ml-auto hidden sm:inline-flex"
                  status={stepStatuses[step.number]}
                />
                {isEdited ? (
                  <Badge
                    className="relative z-10 hidden border sm:inline-flex"
                    variant="outline"
                  >
                    edited
                  </Badge>
                ) : null}
              </Button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

function StepStatusMark({
  isActive,
  shouldReduceMotion,
  status,
  stepNumber,
}: {
  isActive: boolean
  shouldReduceMotion: boolean
  status: NormalizedStatus
  stepNumber: number
}) {
  const isComplete = status === "done"
  const hasError = status === "error"
  const isRunning = status === "running"

  return (
    <span
      className={cn(
        "relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full border bg-background text-xs font-medium transition-colors",
        isActive && "border-primary/35 shadow-sm",
        status === "pending" && "border-border text-muted-foreground",
        isComplete &&
          "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
        hasError &&
          "border-destructive/30 bg-destructive/10 text-destructive",
        isRunning &&
          "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300"
      )}
    >
      {isRunning ? (
        <>
          <span
            aria-hidden="true"
            className="absolute -inset-1 rounded-full border border-sky-500/35 animate-pulse-ring"
          />
          <span
            aria-hidden="true"
            className="absolute -inset-0.5 rounded-full border-2 border-sky-500/70 border-t-transparent motion-safe:animate-spin motion-reduce:animate-none"
          />
        </>
      ) : null}
      <AnimatePresence mode="wait" initial={false}>
        {isComplete ? (
          <motion.span
            animate={{ opacity: 1, rotate: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.85 }}
            initial={
              shouldReduceMotion
                ? false
                : { opacity: 0, rotate: -12, scale: 0.7 }
            }
            key="done"
            transition={{ duration: shouldReduceMotion ? 0 : 0.18 }}
          >
            <CheckIcon className="size-4" />
          </motion.span>
        ) : hasError ? (
          <motion.span
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.85 }}
            initial={shouldReduceMotion ? false : { opacity: 0, scale: 0.7 }}
            key="error"
            transition={{ duration: shouldReduceMotion ? 0 : 0.18 }}
          >
            <XIcon className="size-4" />
          </motion.span>
        ) : (
          <motion.span
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.85 }}
            initial={shouldReduceMotion ? false : { opacity: 0, scale: 0.85 }}
            key={isRunning ? "running" : "pending"}
            transition={{ duration: shouldReduceMotion ? 0 : 0.16 }}
          >
            {stepNumber}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  )
}
