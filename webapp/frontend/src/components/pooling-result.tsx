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
import { CountUp } from "@/components/react-bits/count-up"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

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
  label: string
}

type PooledSummary = {
  ciLower: number | null
  ciUpper: number | null
  i2: number | null
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

export function PoolingResult({
  forestRows,
  forestStatus = "ready",
  pooledRows,
}: PoolingResultProps) {
  const pooled = readPooledSummary(pooledRows)
  const forest = readForestRows(forestRows)
  const xDomain = getXDomain(forest, pooled)
  const chartHeight = Math.max(280, forest.length * 46 + 96)

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {summaryStats.map((stat) => (
          <Card key={stat.key} size="sm">
            <CardHeader>
              <CardDescription>{stat.label}</CardDescription>
              <CardTitle className="font-mono text-lg">
                <SummaryValue pooled={pooled} statKey={stat.key} />
              </CardTitle>
            </CardHeader>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <CardTitle>Forest plot</CardTitle>
              <CardDescription>
                Per-study point estimates with 95% confidence intervals.
              </CardDescription>
            </div>
            <Badge variant="outline">
              {forest.length > 0 ? `${forest.length} rows` : "no forest rows"}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          {forest.length > 0 && xDomain ? (
            <div className="w-full overflow-x-auto">
              <div className="min-w-[640px]" style={{ height: chartHeight }}>
                <ResponsiveContainer height="100%" width="100%">
                  <ComposedChart
                    accessibilityLayer
                    data={forest}
                    layout="vertical"
                    margin={{ bottom: 12, left: 12, right: 24, top: 12 }}
                  >
                    <CartesianGrid horizontal={false} strokeDasharray="3 3" />
                    <XAxis
                      allowDataOverflow
                      domain={xDomain}
                      tickFormatter={formatNumber}
                      type="number"
                    />
                    <YAxis
                      dataKey="label"
                      interval={0}
                      tick={{ fontSize: 12 }}
                      tickLine={false}
                      type="category"
                      width={150}
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
                          key={`ci-${row.label}`}
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

function readPooledSummary(rows: StepTableRows): PooledSummary {
  const row = rows.rows[0] ?? {}
  return {
    ciLower: readNumber(row.ci_lower),
    ciUpper: readNumber(row.ci_upper),
    i2: readNumber(row.i2),
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

function countUpDecimals(value: number): number {
  return Number.isInteger(value) ? 0 : 3
}

// Animates numeric pooled stats on first view (React Bits CountUp); the CI
// range and any "-" placeholders fall back to the plain formatted string.
function SummaryValue({
  statKey,
  pooled,
}: {
  statKey: (typeof summaryStats)[number]["key"]
  pooled: PooledSummary
}) {
  if (statKey === "ci") {
    return <>{formatSummaryValue(statKey, pooled)}</>
  }

  if (statKey === "i2") {
    return pooled.i2 !== null ? (
      <CountUp decimals={countUpDecimals(pooled.i2)} suffix="%" to={pooled.i2} />
    ) : (
      <>-</>
    )
  }

  const value = getPooledStatValue(statKey, pooled)
  return value !== null ? (
    <CountUp decimals={countUpDecimals(value)} to={value} />
  ) : (
    <>-</>
  )
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
