import { Badge } from "@/components/ui/badge"
import {
  getStatusClassName,
  getStatusLabel,
  normalizeStatus,
} from "@/lib/status"
import { cn } from "@/lib/utils"

type StatusBadgeProps = {
  className?: string
  label?: string
  showDot?: boolean
  status: string | null | undefined
}

export function StatusBadge({
  className,
  label,
  showDot = true,
  status,
}: StatusBadgeProps) {
  const normalized = normalizeStatus(status)

  return (
    <Badge
      className={cn(
        "border capitalize",
        getStatusClassName(status),
        className
      )}
      variant="outline"
    >
      {showDot ? (
        <span
          aria-hidden="true"
          className={cn(
            "size-1.5 rounded-full",
            normalized === "pending" && "bg-muted-foreground/45",
            normalized === "running" &&
              "bg-sky-500 motion-safe:animate-pulse",
            normalized === "done" && "bg-emerald-500",
            normalized === "error" && "bg-destructive"
          )}
        />
      ) : null}
      {label ?? getStatusLabel(status)}
    </Badge>
  )
}
