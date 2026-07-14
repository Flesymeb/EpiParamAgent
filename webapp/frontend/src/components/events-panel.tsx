import { useEffect, useMemo, useRef, useState } from "react"
import {
  ArrowDownIcon,
  CircleAlertIcon,
  CircleXIcon,
  InfoIcon,
  RadioIcon,
  SearchIcon,
  XIcon,
} from "lucide-react"
import { motion, useReducedMotion } from "motion/react"

import type { RunEvent } from "@/api/events"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"

type EventsPanelProps = {
  connectionStatus: EventConnectionStatus
  events: RunEvent[]
}

type EventLevelFilter = "all" | "info" | "warn" | "error"
type EventConnectionStatus = "live" | "paused" | "offline"

const EVENT_FILTERS: Array<{ label: string; value: EventLevelFilter }> = [
  { label: "All", value: "all" },
  { label: "Info", value: "info" },
  { label: "Warn", value: "warn" },
  { label: "Error", value: "error" },
]

export function EventsPanel({ connectionStatus, events }: EventsPanelProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const [levelFilter, setLevelFilter] = useState<EventLevelFilter>("all")
  const [query, setQuery] = useState("")
  const [autoScroll, setAutoScroll] = useState(true)
  const shouldReduceMotion = useReducedMotion()
  const normalizedQuery = query.trim().toLowerCase()
  const eventCounts = useMemo(() => countEventLevels(events), [events])
  const filteredEvents = useMemo(() => {
    const levelFilteredEvents =
      levelFilter === "all"
        ? events
        : events.filter(
            (event) => normalizeEventLevel(event.level) === levelFilter
          )

    if (!normalizedQuery) {
      return levelFilteredEvents
    }

    return levelFilteredEvents.filter((event) =>
      getSearchText(event).includes(normalizedQuery)
    )
  }, [events, levelFilter, normalizedQuery])
  const eventPaneHeight = getEventPaneHeight(
    events.length,
    filteredEvents.length
  )

  useEffect(() => {
    if (!autoScroll) {
      return
    }

    bottomRef.current?.scrollIntoView({
      behavior: shouldReduceMotion ? "auto" : "smooth",
      block: "end",
    })
  }, [autoScroll, filteredEvents.length, shouldReduceMotion])

  return (
    <Card aria-label="Run events" className="gap-0 overflow-hidden py-0">
      <div className="flex items-center gap-2 border-b border-border/70 bg-muted/20 px-3 py-2 sm:px-4 sm:py-2.5">
        <RadioIcon className="size-4 shrink-0 text-primary" />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          Run events
        </span>
        {events.length > 0 ? (
          <span className="text-xs text-muted-foreground">
            {filteredEvents.length}/{events.length}
          </span>
        ) : null}
        <LiveIndicator status={connectionStatus} />
      </div>
      <div className="space-y-2.5 p-3 sm:space-y-3 sm:p-4">
        {events.length > 0 ? (
          <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div className="grid grid-cols-2 gap-1.5 sm:flex sm:flex-wrap sm:items-center">
              {EVENT_FILTERS.map((filter) => (
                <Button
                  aria-pressed={levelFilter === filter.value}
                  className={cn(
                    "w-full justify-center gap-1.5 sm:w-auto",
                    levelFilter === filter.value &&
                      "border-primary/35 bg-primary/10 text-primary hover:bg-primary/15"
                  )}
                  key={filter.value}
                  onClick={() => setLevelFilter(filter.value)}
                  size="default"
                  type="button"
                  variant={levelFilter === filter.value ? "outline" : "ghost"}
                >
                  {filter.label}
                  <span className="rounded-full border border-border/70 bg-background px-1.5 text-[0.65rem] leading-4 text-muted-foreground">
                    {eventCounts[filter.value]}
                  </span>
                </Button>
              ))}
            </div>
            <div className="flex min-w-0 flex-col items-stretch gap-2 sm:flex-row sm:items-center">
              <div className="relative min-w-0 w-full sm:w-72 sm:flex-none">
                <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  aria-label="Search events"
                  className="h-8 bg-background pl-8 pr-8 text-sm"
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search events"
                  value={query}
                />
                {query ? (
                  <Button
                    aria-label="Clear event search"
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
              <Button
                aria-pressed={autoScroll}
                className={cn(
                  "shrink-0 gap-1.5 self-end sm:self-auto",
                  autoScroll &&
                    "border-primary/35 bg-primary/10 text-primary hover:bg-primary/15"
                )}
                onClick={() => setAutoScroll((current) => !current)}
                size="default"
                type="button"
                variant={autoScroll ? "outline" : "ghost"}
              >
                <ArrowDownIcon className="size-3.5" />
                Follow
              </Button>
            </div>
          </div>
        ) : null}
        <div className="relative">
          <ScrollArea className="pr-3" style={{ height: eventPaneHeight }}>
            {events.length === 0 ? (
              <div className="flex h-full min-h-[180px] items-center justify-center rounded-lg border border-dashed bg-muted/25 p-6 text-center">
                <div className="flex max-w-56 flex-col items-center gap-2 text-sm text-muted-foreground">
                  <RadioIcon className="size-5 opacity-70" />
                  <p>Waiting for run events.</p>
                  <p className="text-xs">
                    New backend messages will appear here as the pipeline moves.
                  </p>
                </div>
              </div>
            ) : filteredEvents.length === 0 ? (
              <div className="flex h-full min-h-[180px] items-center justify-center rounded-lg border border-dashed bg-muted/25 p-6 text-center">
                <div className="flex max-w-56 flex-col items-center gap-2 text-sm text-muted-foreground">
                  <RadioIcon className="size-5 opacity-70" />
                  <p>
                    No events match
                    {query ? ` "${query}"` : ` ${levelFilter}`}.
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                {filteredEvents.map((event, index) => {
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
                            className={cn(
                              "border uppercase",
                              level.badgeClassName
                            )}
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
          {filteredEvents.length > 0 ? (
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
      </div>
    </Card>
  )
}

function getEventPaneHeight(totalEvents: number, visibleEvents: number) {
  if (totalEvents === 0 || visibleEvents === 0) {
    return 220
  }

  return Math.min(360, Math.max(112, visibleEvents * 72 + 8))
}

function LiveIndicator({ status }: { status: EventConnectionStatus }) {
  const label =
    status === "live" ? "Live" : status === "paused" ? "Paused" : "Offline"

  return (
    <Badge
      className={cn(
        "border",
        status === "live"
          ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
          : status === "paused"
            ? "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300"
          : "border-border bg-muted text-muted-foreground"
      )}
      title={
        status === "paused"
          ? "Live event streaming is paused for this view."
          : undefined
      }
      variant="outline"
    >
      <span
        aria-hidden="true"
        className={cn(
          "size-1.5 rounded-full",
          status === "live"
            ? "bg-emerald-500 motion-safe:animate-pulse"
            : status === "paused"
              ? "bg-amber-500"
            : "bg-muted-foreground/45"
        )}
      />
      {label}
    </Badge>
  )
}

function getSearchText(event: RunEvent) {
  return [
    event.message,
    event.level,
    event.step_no === null ? "" : `step ${event.step_no}`,
    formatEventTime(event.ts),
    formatEventDateTime(event.ts),
  ]
    .join(" ")
    .toLowerCase()
}

function countEventLevels(events: RunEvent[]) {
  const counts: Record<EventLevelFilter, number> = {
    all: events.length,
    error: 0,
    info: 0,
    warn: 0,
  }

  events.forEach((event) => {
    counts[normalizeEventLevel(event.level)] += 1
  })

  return counts
}

function normalizeEventLevel(level: string): Exclude<EventLevelFilter, "all"> {
  const normalized = level.toLowerCase()

  if (normalized === "error") {
    return "error"
  }

  if (normalized === "warn" || normalized === "warning") {
    return "warn"
  }

  return "info"
}

function getLevelStyles(level: string) {
  const normalized = normalizeEventLevel(level)

  if (normalized === "error") {
    return {
      badgeClassName: "border-destructive/30 text-destructive",
      icon: CircleXIcon,
      iconClassName: "text-destructive",
      label: "error",
    }
  }

  if (normalized === "warn") {
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
