import type { ReactNode } from "react"
import { CircleHelpIcon } from "lucide-react"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

type HintTooltipProps = {
  content: ReactNode
  className?: string
  label?: string
}

// A small "?" affordance that reveals a short hint on hover/focus. Relies on the
// app-level TooltipProvider (see App.tsx). Rendered as a type="button" so it is
// safe to place inside <form> elements without triggering submit.
export function HintTooltip({
  content,
  className,
  label = "More info",
}: HintTooltipProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          aria-label={label}
          className={cn(
            "inline-flex size-7 shrink-0 items-center justify-center rounded-full text-muted-foreground/70 outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50",
            className
          )}
          type="button"
        >
          <CircleHelpIcon className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-xs leading-relaxed">
        {content}
      </TooltipContent>
    </Tooltip>
  )
}
