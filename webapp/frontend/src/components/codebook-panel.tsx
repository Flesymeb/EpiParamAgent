import { useEffect, useState } from "react"
import { BookOpenIcon, ChevronsUpDownIcon, LoaderCircleIcon } from "lucide-react"

import { getCodebook } from "@/api/codebook"
import type { Codebook } from "@/api/codebook"
import { Badge } from "@/components/ui/badge"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { getErrorMessage } from "@/lib/errors"

type CodebookState =
  | { key: string; status: "idle" | "loading"; data: null; error: null }
  | { key: string; status: "ready"; data: Codebook; error: null }
  | { key: string; status: "error"; data: null; error: string }

type CodebookPanelProps = {
  disease: string
  parameter: string
  overridePath?: string
}

// Read-only preview of the codebook a coding run will extract against, so the
// reviewer can see exactly which fields the LLM is asked to fill before running.
export function CodebookPanel({
  disease,
  parameter,
  overridePath,
}: CodebookPanelProps) {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<CodebookState>({
    key: "",
    status: "idle",
    data: null,
    error: null,
  })
  const key = `${disease}|${parameter}`
  const hasSelection = Boolean(disease && parameter)

  // Derive what to show during render so the effect only setState()s from async
  // resolution (avoids synchronous setState-in-effect).
  const visibleState: CodebookState =
    state.key === key
      ? state
      : hasSelection
        ? { key, status: "loading", data: null, error: null }
        : { key, status: "idle", data: null, error: null }

  useEffect(() => {
    if (!hasSelection) {
      return
    }

    const controller = new AbortController()

    getCodebook(disease, parameter, controller.signal)
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
  }, [disease, parameter, key, hasSelection])

  const data = visibleState.status === "ready" ? visibleState.data : null
  const fieldCount = data?.fields.length ?? 0

  return (
    <div className="rounded-lg border bg-background">
      <Collapsible onOpenChange={setOpen} open={open}>
        <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm font-medium transition-colors hover:bg-muted/40">
          <BookOpenIcon className="size-4 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate">
            Codebook
            {data?.name ? (
              <span className="ml-1 font-normal text-muted-foreground">
                · {data.name}
              </span>
            ) : null}
          </span>
          {visibleState.status === "loading" ? (
            <LoaderCircleIcon className="size-4 text-muted-foreground motion-safe:animate-spin motion-reduce:animate-none" />
          ) : null}
          {fieldCount > 0 ? (
            <Badge className="font-normal" variant="secondary">
              {fieldCount} fields
            </Badge>
          ) : null}
          <ChevronsUpDownIcon className="size-4 text-muted-foreground" />
        </CollapsibleTrigger>
        <CollapsibleContent className="border-t">
          <CodebookBody state={visibleState} />
        </CollapsibleContent>
      </Collapsible>
      {overridePath ? (
        <p className="border-t px-3 py-2 text-[0.7rem] text-amber-600 dark:text-amber-400">
          Custom codebook path set — preview shows the default {parameter}{" "}
          codebook, not the override.
        </p>
      ) : null}
    </div>
  )
}

function CodebookBody({ state }: { state: CodebookState }) {
  if (state.status === "idle") {
    return (
      <p className="px-3 py-3 text-xs text-muted-foreground">
        Select a disease and parameter to preview its codebook.
      </p>
    )
  }

  if (state.status === "loading") {
    return (
      <p className="px-3 py-3 text-xs text-muted-foreground">
        Loading codebook…
      </p>
    )
  }

  if (state.status === "error") {
    return (
      <p className="px-3 py-3 text-xs text-muted-foreground">
        Couldn't load codebook: {state.error}
      </p>
    )
  }

  if (state.status !== "ready") {
    return null
  }

  const { data } = state

  return (
    <div className="space-y-3 px-3 py-3">
      {data.description ? (
        <p className="text-xs text-muted-foreground">{data.description}</p>
      ) : null}
      {data.notes ? (
        <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2 text-[0.7rem] leading-relaxed text-muted-foreground">
          {data.notes.trim()}
        </pre>
      ) : null}
      {data.fields.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No fields defined in this codebook.
        </p>
      ) : (
        <ul className="divide-y rounded-md border">
          {data.fields.map((field, index) => (
            <li
              className="flex flex-col gap-0.5 px-2.5 py-2"
              key={field.name ?? field.label ?? `field-${index}`}
            >
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-xs font-medium">
                  {field.label || field.name}
                </span>
                {field.type ? (
                  <Badge className="font-normal" variant="outline">
                    {field.type}
                  </Badge>
                ) : null}
                {field.required ? (
                  <span className="text-[0.65rem] font-medium text-amber-600 dark:text-amber-400">
                    required
                  </span>
                ) : null}
              </div>
              {field.prompt ? (
                <p className="text-[0.7rem] leading-relaxed text-muted-foreground">
                  {field.prompt}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
