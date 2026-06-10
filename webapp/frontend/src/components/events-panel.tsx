import { useEffect, useRef } from "react"
import {
  CircleAlertIcon,
  CircleXIcon,
  InfoIcon,
  RadioIcon,
} from "lucide-react"
import { motion, useReducedMotion } from "motion/react"

import type { RunEvent } from "@/api/events"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"

type EventsPanelProps = {
  events: RunEvent[]
  isConnected: boolean
}

export function EventsPanel({ events, isConnected }: EventsPanelProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const shouldReduceMotion = useReducedMotion()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: shouldReduceMotion ? "auto" : "smooth",
      block: "end",
    })
  }, [events.length, shouldReduceMotion])

  return (
    <Card className="min-h-[320px]">
      <CardHeader>
        <CardTitle>Events</CardTitle>
        <CardDescription className="flex items-center gap-2">
          <span>Live run log</span>
          <LiveIndicator isConnected={isConnected} />
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="relative">
          <ScrollArea className="h-[360px] pr-3">
          {events.length === 0 ? (
            <div className="flex h-[320px] items-center justify-center rounded-lg border border-dashed bg-muted/25 p-6 text-center">
              <div className="flex max-w-56 flex-col items-center gap-2 text-sm text-muted-foreground">
                <RadioIcon className="size-5 opacity-70" />
                <p>Waiting for run events.</p>
                <p className="text-xs">
                  New backend messages will appear here as the pipeline moves.
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {events.map((event, index) => {
                const level = getLevelStyles(event.level)
                const Icon = level.icon

                return (
                  <motion.div
                    animate={{ opacity: 1, y: 0 }}
                    className="grid grid-cols-[auto_1fr] gap-3 rounded-md px-1.5 py-1.5 text-sm transition-colors animate-fade-slide-in hover:bg-muted/35"
                    initial={
                      shouldReduceMotion ? false : { opacity: 0, y: 6 }
                    }
                    key={event.id}
                    transition={{
                      delay: shouldReduceMotion
                        ? 0
                        : Math.min(index * 0.012, 0.12),
                      duration: shouldReduceMotion ? 0 : 0.2,
                      ease: "easeOut",
                    }}
                  >
                    <Icon className={cn("mt-1 size-4", level.iconClassName)} />
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <Badge
                          className={cn("border uppercase", level.badgeClassName)}
                          variant="outline"
                        >
                          {level.label}
                        </Badge>
                        <span
                          className="truncate text-xs text-muted-foreground"
                          title={formatEventDateTime(event.ts)}
                        >
                          {formatEventTime(event.ts)}
                        </span>
                      </div>
                      <p className="mt-1 break-words text-foreground">
                        {event.message}
                      </p>
                      {event.step_no !== null ? (
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          Step {event.step_no}
                        </p>
                      ) : null}
                    </div>
                  </motion.div>
                )
              })}
              <div ref={bottomRef} />
            </div>
          )}
          </ScrollArea>
          {events.length > 0 ? (
            <>
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-x-0 top-0 z-10 h-6 bg-gradient-to-b from-card to-transparent"
              />
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-6 bg-gradient-to-t from-card to-transparent"
              />
            </>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

function LiveIndicator({ isConnected }: { isConnected: boolean }) {
  return (
    <Badge
      className={cn(
        "border",
        isConnected
          ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
          : "border-border bg-muted text-muted-foreground"
      )}
      variant="outline"
    >
      <span
        aria-hidden="true"
        className={cn(
          "size-1.5 rounded-full",
          isConnected
            ? "bg-emerald-500 motion-safe:animate-pulse"
            : "bg-muted-foreground/45"
        )}
      />
      {isConnected ? "Live" : "offline"}
    </Badge>
  )
}

function getLevelStyles(level: string) {
  const normalized = level.toLowerCase()

  if (normalized === "error") {
    return {
      badgeClassName: "border-destructive/30 text-destructive",
      icon: CircleXIcon,
      iconClassName: "text-destructive",
      label: "error",
    }
  }

  if (normalized === "warn" || normalized === "warning") {
    return {
      badgeClassName: "border-amber-500/30 text-amber-700 dark:text-amber-300",
      icon: CircleAlertIcon,
      iconClassName: "text-amber-700 dark:text-amber-300",
      label: "warn",
    }
  }

  return {
    badgeClassName: "border-border text-muted-foreground",
    icon: InfoIcon,
    iconClassName: "text-muted-foreground",
    label: "info",
  }
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

function formatEventDateTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return date.toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "medium",
  })
}
