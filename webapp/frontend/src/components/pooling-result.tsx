import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  XAxis,
  YAxis,
} from "recharts"

import type { StepTableRows } from "@/api/client/types.gen"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useIsMobile } from "@/hooks/use-mobile"

type PoolingResultProps = {
  forestRows: StepTableRows | null
  forestStatus?: "loading" | "missing" | "ready"
  pooledRows: StepTableRows
}

type ForestDatum = {
  ci: [number, number] | null
  ciLower: number | null
  ciUpper: number | null
  estimate: number | null
  id: string
  label: string
}

type PooledSummary = {
  ciLower: number | null
  ciUpper: number | null
  i2: number | null
  nExcluded: number | null
  nImputed: number | null
  nStudies: number | null
  pooledEstimate: number | null
  q: number | null
  tau2: number | null
}

const summaryStats = [
  { key: "pooledEstimate", label: "Pooled Estimate" },
  { key: "ci", label: "95% CI" },
  { key: "i2", label: "I²" },
  { key: "tau2", label: "τ²" },
  { key: "q", label: "Q" },
  { key: "nStudies", label: "Studies" },
] as const

const forestPlotMargin = { bottom: 12, left: 12, right: 24, top: 12 } as const
const compactForestPlotMargin = {
  bottom: 12,
  left: 8,
  right: 16,
  top: 12,
} as const
const forestYAxisWidth = 150
const compactForestYAxisWidth = 112

export function PoolingResult({
  forestRows,
  forestStatus = "ready",
  pooledRows,
}: PoolingResultProps) {
  const isMobile = useIsMobile()
  const pooled = readPooledSummary(pooledRows)
  const forest = readForestRows(forestRows)
  const xDomain = getXDomain(forest, pooled)
  const chartHeight = Math.max(280, forest.length * 46 + 96)
  const chartMinWidth = isMobile ? 540 : 640
  const yAxisWidth = isMobile ? compactForestYAxisWidth : forestYAxisWidth
  const chartMargin = isMobile ? compactForestPlotMargin : forestPlotMargin
  const forestBadgeLabel = formatForestBadge(forest.length, pooled.nStudies)
  const isPartialForest =
    forest.length > 0 &&
    pooled.nStudies !== null &&
    forest.length < pooled.nStudies

  return (
    <div className="space-y-4">
      <div className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        {summaryStats.map((stat) => (
          <div
            className="min-w-0 rounded-lg border border-border/70 bg-muted/15 px-2.5 py-2 shadow-xs sm:px-3"
            key={stat.key}
          >
            <div className="truncate text-xs text-muted-foreground">
              {stat.label}
            </div>
            <div className="mt-0.5 break-words font-mono text-sm font-medium leading-snug sm:text-base">
              {formatSummaryValue(stat.key, pooled)}
            </div>
          </div>
        ))}
      </div>
      <PoolingQualityStrip plottedCount={forest.length} pooled={pooled} />

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <CardTitle>Forest plot</CardTitle>
              <CardDescription>
                {isPartialForest
                  ? "Plottable study estimates from forest.csv; pooled total includes additional studies."
                  : "Plottable study estimates from forest.csv with 95% confidence intervals."}
              </CardDescription>
            </div>
            <Badge className="font-normal" variant="outline">
              {forestBadgeLabel}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          {forest.length > 0 && xDomain ? (
            <div className="space-y-2">
              <ForestPlotLegend />
              <div className="max-h-[min(46vh,420px)] w-full overflow-auto overscroll-contain rounded-lg border border-border/70 bg-background/50 sm:max-h-[min(72vh,720px)]">
                <div className="w-full" style={{ minWidth: chartMinWidth }}>
                  <ForestPlotScaleBar
                    domain={xDomain}
                    margin={chartMargin}
                    tickCount={isMobile ? 3 : 5}
                    yAxisWidth={yAxisWidth}
                  />
                  <div style={{ height: chartHeight }}>
                    <ResponsiveContainer
                      height="100%"
                      initialDimension={{
                        height: chartHeight,
                        width: chartMinWidth,
                      }}
                      minHeight={chartHeight}
                      minWidth={chartMinWidth}
                      width="100%"
                    >
                      <ComposedChart
                        accessibilityLayer
                        data={forest}
                        layout="vertical"
                        margin={chartMargin}
                      >
                        <CartesianGrid horizontal={false} strokeDasharray="3 3" />
                        <XAxis
                          allowDataOverflow
                          domain={xDomain}
                          hide
                          tickFormatter={formatNumber}
                          type="number"
                        />
                        <YAxis
                          dataKey="label"
                          interval={0}
                          tick={{ fontSize: isMobile ? 11 : 12 }}
                          tickLine={false}
                          type="category"
                          width={yAxisWidth}
                        />
                        {pooled.ciLower !== null && pooled.ciUpper !== null ? (
                          <ReferenceArea
                            fill="var(--muted-foreground)"
                            fillOpacity={0.08}
                            ifOverflow="extendDomain"
                            x1={pooled.ciLower}
                            x2={pooled.ciUpper}
                          />
                        ) : null}
                        {pooled.pooledEstimate !== null ? (
                          <ReferenceLine
                            ifOverflow="extendDomain"
                            stroke="var(--foreground)"
                            strokeDasharray="4 4"
                            strokeWidth={1.5}
                            x={pooled.pooledEstimate}
                          />
                        ) : null}
                        <Bar
                          dataKey="ci"
                          fill="var(--muted-foreground)"
                          isAnimationActive={false}
                          radius={3}
                        >
                          {forest.map((row) => (
                            <Cell
                              fillOpacity={row.ci ? 0.38 : 0}
                              key={`ci-${row.id}`}
                            />
                          ))}
                        </Bar>
                        <Scatter
                          dataKey="estimate"
                          fill="var(--foreground)"
                          isAnimationActive={false}
                          line={false}
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            </div>
          ) : forestStatus === "loading" ? (
            <ForestPlotSkeleton />
          ) : (
            <div className="rounded-lg border border-dashed bg-muted/20 p-6 text-sm text-muted-foreground">
              {forestStatus === "missing"
                ? "forest.csv is not available for this run yet. Showing pooled statistics only."
                : "forest.csv has no plottable estimate rows. Showing pooled statistics only."}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function ForestPlotLegend() {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border/60 bg-muted/15 px-2.5 py-2 text-[0.7rem] text-muted-foreground sm:px-3 sm:text-xs">
      <span className="inline-flex items-center gap-1.5">
        <span className="h-px w-5 border-t border-dashed border-foreground" />
        Pooled estimate
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-5 rounded-sm bg-muted-foreground/15 ring-1 ring-muted-foreground/20" />
        Pooled 95% CI
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="size-2 rounded-full bg-foreground" />
        Study estimate
      </span>
    </div>
  )
}

function PoolingQualityStrip({
  plottedCount,
  pooled,
}: {
  plottedCount: number
  pooled: PooledSummary
}) {
  const items = [
    plottedCount > 0
      ? {
          label: "Forest rows",
          value: formatNumber(plottedCount),
          detail:
            pooled.nStudies !== null && pooled.nStudies > plottedCount
              ? `of ${formatNumber(pooled.nStudies)} studies`
              : "plotted",
        }
      : null,
    pooled.nExcluded !== null
      ? {
          label: "Excluded",
          value: formatNumber(pooled.nExcluded),
          detail: "from pooling",
        }
      : null,
    pooled.nImputed !== null
      ? {
          label: "Imputed",
          value: formatNumber(pooled.nImputed),
          detail: "values",
        }
      : null,
  ].filter((item): item is { detail: string; label: string; value: string } =>
    Boolean(item)
  )

  if (items.length === 0) {
    return null
  }

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-border/70 bg-muted/10 px-2.5 py-2 text-xs text-muted-foreground sm:px-3">
      <span className="font-medium text-foreground">Input checks</span>
      {items.map((item) => (
        <span
          className="inline-flex min-w-0 items-center gap-1 rounded-md border border-border/60 bg-background/70 px-2 py-1"
          key={item.label}
        >
          <span>{item.label}</span>
          <span className="font-mono font-medium text-foreground">
            {item.value}
          </span>
          <span className="hidden sm:inline">{item.detail}</span>
        </span>
      ))}
    </div>
  )
}

function ForestPlotSkeleton() {
  return (
    <div
      aria-busy="true"
      className="rounded-lg border border-dashed bg-muted/20 p-4"
    >
      <div className="space-y-3">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-11/12" />
        <Skeleton className="h-8 w-4/5" />
        <Skeleton className="h-8 w-3/5" />
      </div>
    </div>
  )
}

function ForestPlotScaleBar({
  domain,
  margin,
  tickCount,
  yAxisWidth,
}: {
  domain: [number, number]
  margin: typeof forestPlotMargin | typeof compactForestPlotMargin
  tickCount: number
  yAxisWidth: number
}) {
  const ticks = buildAxisTicks(domain, tickCount)

  return (
    <div className="sticky top-0 z-20 border-b border-border/70 bg-background/95 py-2 backdrop-blur">
      <div
        className="relative h-6"
        style={{
          paddingLeft: yAxisWidth + margin.left,
          paddingRight: margin.right,
        }}
      >
        <div className="relative h-full border-t border-border/80">
          {ticks.map((tick) => (
            <span
              className="absolute top-0 flex -translate-x-1/2 flex-col items-center gap-1 text-[0.68rem] leading-none text-muted-foreground"
              key={tick.value}
              style={{ left: `${tick.position}%` }}
            >
              <span className="h-1.5 w-px bg-border" />
              <span className="font-mono">{formatNumber(tick.value)}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

function readPooledSummary(rows: StepTableRows): PooledSummary {
  const row = rows.rows[0] ?? {}
  return {
    ciLower: readNumber(row.ci_lower),
    ciUpper: readNumber(row.ci_upper),
    i2: readNumber(row.i2),
    nExcluded: readNumber(row.n_excluded),
    nImputed: readNumber(row.n_imputed),
    nStudies: readNumber(row.n_studies),
    pooledEstimate: readNumber(row.pooled_mean ?? row.estimate),
    q: readNumber(row.Q ?? row.q),
    tau2: readNumber(row.tau2),
  }
}

function readForestRows(rows: StepTableRows | null): ForestDatum[] {
  if (!rows) {
    return []
  }

  return rows.rows
    .map((row, index) => {
      const label = row.study_label?.trim() || `row ${index + 1}`
      const estimate = readNumber(row.estimate)
      const ciLower = readNumber(row.ci_lower)
      const ciUpper = readNumber(row.ci_upper)
      return {
        ci:
          ciLower !== null && ciUpper !== null && ciUpper >= ciLower
            ? ([ciLower, ciUpper] satisfies [number, number])
            : null,
        ciLower,
        ciUpper,
        estimate,
        id: `${index}-${label}-${row.estimate ?? ""}-${row.ci_lower ?? ""}-${row.ci_upper ?? ""}`,
        label,
      }
    })
    .filter((row) => row.estimate !== null)
}

function getXDomain(
  forest: ForestDatum[],
  pooled: PooledSummary,
): [number, number] | null {
  const values = [
    ...forest.flatMap((row) => [row.ciLower, row.estimate, row.ciUpper]),
    pooled.ciLower,
    pooled.pooledEstimate,
    pooled.ciUpper,
  ].filter((value): value is number => value !== null)

  if (values.length === 0) {
    return null
  }

  const min = Math.min(...values)
  const max = Math.max(...values)
  if (min === max) {
    const pad = Math.max(Math.abs(min) * 0.1, 1)
    return [min - pad, max + pad]
  }

  const pad = (max - min) * 0.12
  return [min - pad, max + pad]
}

function buildAxisTicks([min, max]: [number, number], count = 5) {
  if (min === max) {
    return [{ position: 50, value: min }]
  }

  const tickCount = Math.max(2, count)
  return Array.from({ length: tickCount }, (_, index) => {
    const ratio = index / (tickCount - 1)
    return {
      position: ratio * 100,
      value: min + (max - min) * ratio,
    }
  })
}

function readNumber(value: string | undefined): number | null {
  if (value === undefined || value.trim() === "") {
    return null
  }

  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatSummaryValue(
  key: (typeof summaryStats)[number]["key"],
  pooled: PooledSummary,
) {
  if (key === "ci") {
    return pooled.ciLower !== null && pooled.ciUpper !== null
      ? `${formatNumber(pooled.ciLower)} to ${formatNumber(pooled.ciUpper)}`
      : "-"
  }

  if (key === "i2") {
    return pooled.i2 !== null ? `${formatNumber(pooled.i2)}%` : "-"
  }

  const value = getPooledStatValue(key, pooled)
  return value !== null ? formatNumber(value) : "-"
}

function formatForestBadge(forestCount: number, totalStudies: number | null) {
  if (forestCount <= 0) {
    return "no plot rows"
  }

  if (totalStudies !== null && totalStudies > forestCount) {
    return `${forestCount} of ${formatNumber(totalStudies)} plotted`
  }

  return `${forestCount} plotted`
}

function getPooledStatValue(
  key: Exclude<(typeof summaryStats)[number]["key"], "ci" | "i2">,
  pooled: PooledSummary,
) {
  if (key === "pooledEstimate") {
    return pooled.pooledEstimate
  }
  if (key === "tau2") {
    return pooled.tau2
  }
  if (key === "q") {
    return pooled.q
  }
  return pooled.nStudies
}

function formatNumber(value: number) {
  return Number.isInteger(value)
    ? String(value)
    : value.toLocaleString(undefined, { maximumFractionDigits: 3 })
}
