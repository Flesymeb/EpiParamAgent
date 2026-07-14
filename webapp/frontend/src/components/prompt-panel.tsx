import { useEffect, useState } from "react"
import { ChevronsUpDownIcon, FileCode2Icon, LoaderCircleIcon } from "lucide-react"

import { getStagePrompt } from "@/api/prompt"
import type { StagePrompt } from "@/api/prompt"
import { Badge } from "@/components/ui/badge"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Textarea } from "@/components/ui/textarea"
import { getErrorMessage } from "@/lib/errors"

type PromptState =
  | { key: string; status: "idle" | "loading"; data: null; error: null }
  | { key: string; status: "ready"; data: StagePrompt; error: null }
  | { key: string; status: "error"; data: null; error: string }

type PromptPanelProps = {
  stage: string
  disease?: string
  parameter?: string
  strategy?: string
  supplement: string
  onSupplementChange: (value: string) => void
  disabled?: boolean
}

// Shows the (read-only) prompt template a stage uses + a free-text "reviewer
// supplement" that is appended to that prompt at run time.
export function PromptPanel({
  stage,
  disease,
  parameter,
  strategy,
  supplement,
  onSupplementChange,
  disabled = false,
}: PromptPanelProps) {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<PromptState>({
    key: "",
    status: "idle",
    data: null,
    error: null,
  })
  const key = `${stage}|${disease ?? ""}|${parameter ?? ""}|${strategy ?? ""}`
  const visibleState: PromptState =
    state.key === key
      ? state
      : { key, status: "loading", data: null, error: null }

  useEffect(() => {
    const controller = new AbortController()

    getStagePrompt(stage, { disease, parameter, strategy }, controller.signal)
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
  }, [key, stage, disease, parameter, strategy])

  const data = visibleState.status === "ready" ? visibleState.data : null

  return (
    <div className="rounded-lg border bg-background">
      <Collapsible onOpenChange={setOpen} open={open}>
        <CollapsibleTrigger className="flex w-full items-start gap-2 px-3 py-2.5 text-left text-sm font-medium transition-colors hover:bg-muted/40">
          <FileCode2Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 space-y-0.5 sm:flex sm:items-baseline sm:gap-1 sm:space-y-0">
            <span className="block">Prompt template</span>
            {data?.source ? (
              <span className="block min-w-0 break-all font-mono text-xs font-normal leading-4 text-muted-foreground sm:truncate">
                · {data.source}
              </span>
            ) : null}
          </span>
          {visibleState.status === "loading" ? (
            <LoaderCircleIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground motion-safe:animate-spin motion-reduce:animate-none" />
          ) : null}
          <ChevronsUpDownIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        </CollapsibleTrigger>
        <CollapsibleContent className="space-y-3 border-t px-3 py-3">
          {visibleState.status === "error" ? (
            <p className="text-xs text-muted-foreground">
              Couldn't load prompt: {visibleState.error}
            </p>
          ) : data && data.has_prompt ? (
            <>
              <PromptSection label="System" text={data.system} />
              <PromptSection label="User" text={data.user} />
              <PromptSection label="Output rules" text={data.output} />
              <p className="text-[0.7rem] text-muted-foreground">
                Placeholders like <code>{"{disease}"}</code> are filled in at run
                time. This template is read-only — use the supplement below to add
                guidance.
              </p>
            </>
          ) : (
            <p className="text-xs text-muted-foreground">
              This stage has no editable LLM prompt.
            </p>
          )}
        </CollapsibleContent>
      </Collapsible>
      <div className="space-y-1.5 border-t p-3">
        <div className="flex items-center justify-between gap-2">
          <label
            className="text-xs font-medium"
            htmlFor={`prompt-supplement-${stage}`}
          >
            Reviewer supplement
          </label>
          {supplement.trim() ? (
            <Badge className="font-normal" variant="secondary">
              appended at run
            </Badge>
          ) : null}
        </div>
        <Textarea
          className="min-h-20 text-sm"
          disabled={disabled}
          id={`prompt-supplement-${stage}`}
          onChange={(event) => onSupplementChange(event.target.value)}
          placeholder="Extra instructions appended to this stage's prompt — e.g. inclusion/exclusion nuances, preferred output conventions, edge cases to watch."
          value={supplement}
        />
      </div>
    </div>
  )
}

function PromptSection({
  label,
  text,
}: {
  label: string
  text: string | null
}) {
  if (!text) {
    return null
  }
  return (
    <div className="space-y-1">
      <div className="text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground/80">
        {label}
      </div>
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2 text-[0.7rem] leading-relaxed">
        {text}
      </pre>
    </div>
  )
}
