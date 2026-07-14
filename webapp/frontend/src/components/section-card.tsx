import type { ReactNode } from "react"
import type { LucideIcon } from "lucide-react"

import { Card } from "@/components/ui/card"

export function RunningProgressBar() {
  return (
    <div
      aria-hidden="true"
      className="absolute inset-x-0 top-0 h-1 overflow-hidden bg-emerald-500/15"
    >
      <span className="block h-full w-2/5 bg-gradient-to-r from-transparent via-emerald-500 to-transparent shadow-[0_0_8px_rgba(16,185,129,0.7)] animate-shimmer" />
    </div>
  )
}

// A titled functional panel ("板块") — header bar with optional mint icon +
// optional action, content below. Used for the parallel run-detail sections.
export function SectionCard({
  title,
  icon: Icon,
  running = false,
  action,
  children,
}: {
  title: string
  icon?: LucideIcon
  running?: boolean
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <Card className="relative min-w-0 gap-0 overflow-hidden py-0">
      {running ? <RunningProgressBar /> : null}
      <div className="flex items-center gap-2 border-b border-border/70 bg-muted/20 px-3 py-2 sm:px-4 sm:py-2.5">
        {Icon ? <Icon className="size-4 shrink-0 text-primary" /> : null}
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {title}
        </span>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      <div className="min-w-0 overflow-x-clip p-3 sm:p-4">{children}</div>
    </Card>
  )
}
