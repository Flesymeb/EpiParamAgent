import {
  Suspense,
  lazy,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  FileBarChart2,
  Microscope,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import { PaperTable } from "@/components/PaperTable";
import { RunList } from "@/components/RunList";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  CountItem,
  ConfusionMatrix,
  ExtractionRunDetail,
  RunSummary,
  ScreeningPapersResponse,
  ScreeningRunDetail,
  SummaryResponse,
} from "@/types";

type ModuleTab = "screening" | "extraction";
type ScreeningViewTab =
  | "overview"
  | "matrix"
  | "failures"
  | "pool"
  | "provenance";
type ExtractionViewTab = "overview" | "outputs" | "provenance";

const BarsPanel = lazy(async () => {
  const mod = await import("@/components/BarsPanel");
  return { default: mod.BarsPanel };
});

const FunnelPanel = lazy(async () => {
  const mod = await import("@/components/FunnelPanel");
  return { default: mod.FunnelPanel };
});

export default function App() {
  const [moduleTab, setModuleTab] = useState<ModuleTab>("screening");
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [screeningRuns, setScreeningRuns] = useState<RunSummary[]>([]);
  const [extractionRuns, setExtractionRuns] = useState<RunSummary[]>([]);
  const [selectedScreeningId, setSelectedScreeningId] = useState<string>();
  const [selectedExtractionId, setSelectedExtractionId] = useState<string>();
  const [screeningDetail, setScreeningDetail] =
    useState<ScreeningRunDetail | null>(null);
  const [screeningPapers, setScreeningPapers] =
    useState<ScreeningPapersResponse | null>(null);
  const [extractionDetail, setExtractionDetail] =
    useState<ExtractionRunDetail | null>(null);
  const [screeningViewTab, setScreeningViewTab] =
    useState<ScreeningViewTab>("overview");
  const [extractionViewTab, setExtractionViewTab] =
    useState<ExtractionViewTab>("overview");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();

  const deferredQuery = useDeferredValue(query);

  async function bootstrap() {
    setLoading(true);
    setError(undefined);
    try {
      const [summaryData, screeningData, extractionData] = await Promise.all([
        api.summary(),
        api.screeningRuns(),
        api.extractionRuns(),
      ]);
      setSummary(summaryData);
      setScreeningRuns(screeningData);
      setExtractionRuns(extractionData);
      setSelectedScreeningId((current) => current ?? screeningData[0]?.id);
      setSelectedExtractionId((current) => current ?? extractionData[0]?.id);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load workbench data.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    if (moduleTab !== "screening") {
      return;
    }
    if (!selectedScreeningId) {
      setScreeningDetail(null);
      setScreeningPapers(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setScreeningPapers(null);
    void api
      .screeningRun(selectedScreeningId)
      .then((detail) => {
        if (!cancelled) {
          setScreeningDetail(detail);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error ?
              err.message
            : "Failed to load screening detail.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [moduleTab, selectedScreeningId]);

  useEffect(() => {
    if (moduleTab !== "screening") {
      return;
    }
    if (!selectedScreeningId) {
      return;
    }
    if (screeningViewTab !== "pool" && screeningViewTab !== "failures") {
      return;
    }
    if (screeningPapers?.run_id === selectedScreeningId) {
      return;
    }
    let cancelled = false;
    setLoading(true);
    void api
      .screeningRunPapers(selectedScreeningId)
      .then((detail) => {
        if (!cancelled) {
          setScreeningPapers(detail);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Failed to load screened papers."
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [moduleTab, screeningPapers?.run_id, screeningViewTab, selectedScreeningId]);

  useEffect(() => {
    if (moduleTab !== "extraction") {
      return;
    }
    if (!selectedExtractionId) {
      setExtractionDetail(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    void api
      .extractionRun(selectedExtractionId)
      .then((detail) => {
        if (!cancelled) {
          setExtractionDetail(detail);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error ?
              err.message
            : "Failed to load extraction detail.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [moduleTab, selectedExtractionId]);

  const filteredPapers = useMemo(() => {
    const rows = screeningPapers?.papers ?? [];
    if (!deferredQuery.trim()) return rows;
    const needle = deferredQuery.toLowerCase();
    return rows.filter((row) =>
      [row.PMID, row.Title, row.Abstract, row.llm_suggest, row.screening_stage]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle)),
    );
  }, [deferredQuery, screeningPapers?.papers]);

  const funnelItems = useMemo<CountItem[]>(() => {
    if (!screeningDetail) return [];
    const pool =
      screeningDetail.metrics.find((item) => item.label === "Pool")?.value ?? 0;
    const matrix = screeningDetail.confusion_matrix;
    const screening = (matrix?.tp ?? 0) + (matrix?.fp ?? 0);
    const gt = (matrix?.tp ?? 0) + (matrix?.fn ?? 0);
    return [
      { label: "Paper Pool", count: pool },
      { label: "Screened Relevant", count: screening },
      { label: "GT", count: gt },
    ].filter((item) => item.count > 0);
  }, [screeningDetail]);

  const failureRows = useMemo(() => {
    const rows = screeningPapers?.papers ?? [];
    const fnRows = rows.filter((row) => {
      const gt = isGroundTruth(row);
      const predictedRelevant = isPredictedRelevant(row);
      return gt && !predictedRelevant;
    });
    const fpRows = rows
      .filter((row) => {
        const gt = isGroundTruth(row);
        const predictedRelevant = isPredictedRelevant(row);
        return !gt && predictedRelevant;
      })
      .sort(
        (a, b) => Number(b.overall_score ?? 0) - Number(a.overall_score ?? 0),
      );
    return {
      fn: fnRows,
      fp: fpRows,
    };
  }, [screeningPapers?.papers]);

  const activeRun = useMemo<Record<string, unknown> | null>(() => {
    if (moduleTab === "screening") {
      return (
        (screeningDetail?.run as Record<string, unknown> | undefined) ?? null
      );
    }
    return (
      (extractionDetail?.run as Record<string, unknown> | undefined) ?? null
    );
  }, [extractionDetail, moduleTab, screeningDetail]);

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-[1680px] px-4 py-5 lg:px-6 xl:px-8">
        <div className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
          <aside className="space-y-5">
            <div className="space-y-2 border-b border-sage-100 px-1 pb-4 pt-2">
              <div className="text-[1.2rem] font-semibold tracking-tight text-slate-950">
                MetaAgent Workbench
              </div>
              <div className="flex flex-wrap gap-4 text-xs text-slate-500">
                <div>
                  Screening
                  <span className="ml-2 font-mono text-sm font-semibold text-slate-900">
                    {summary?.screening_runs ?? 0}
                  </span>
                </div>
                <div>
                  Extraction
                  <span className="ml-2 font-mono text-sm font-semibold text-slate-900">
                    {summary?.extraction_runs ?? 0}
                  </span>
                </div>
              </div>
            </div>

            <Card className="p-3">
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setModuleTab("screening")}
                  className={cn(
                    "rounded-sm px-4 py-3 text-sm font-semibold transition",
                    moduleTab === "screening" ?
                      "bg-sage-700 text-white shadow-soft"
                    : "bg-sage-50 text-slate-700 hover:bg-sage-100",
                  )}
                >
                  Screening
                </button>
                <button
                  type="button"
                  onClick={() => setModuleTab("extraction")}
                  className={cn(
                    "rounded-sm px-4 py-3 text-sm font-semibold transition",
                    moduleTab === "extraction" ?
                      "bg-earth-600 text-white shadow-soft"
                    : "bg-earth-50 text-slate-700 hover:bg-earth-100",
                  )}
                >
                  Extraction
                </button>
              </div>
            </Card>

            {moduleTab === "screening" ?
              <RunList
                runs={screeningRuns}
                selectedId={selectedScreeningId}
                onSelect={setSelectedScreeningId}
                title="Screening Runs"
              />
            : <RunList
                runs={extractionRuns}
                selectedId={selectedExtractionId}
                onSelect={setSelectedExtractionId}
                title="Extraction Runs"
              />
            }
          </aside>

          <main className="space-y-5">
            <Hero
              moduleTab={moduleTab}
              onRefresh={() => void bootstrap()}
              loading={loading}
              activeRun={activeRun}
            />

            {error ?
              <Card className="border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
                {error}
              </Card>
            : null}

            {moduleTab === "screening" ?
              <>
                <SectionNav
                  activeId={screeningViewTab}
                  onSelect={(id) => setScreeningViewTab(id as ScreeningViewTab)}
                  items={[
                    { id: "overview", label: "Overview" },
                    { id: "matrix", label: "Confusion Matrix" },
                    { id: "failures", label: "Failure Cases" },
                    { id: "pool", label: "Paper Pool" },
                    { id: "provenance", label: "Provenance" },
                  ]}
                />

                {screeningViewTab === "overview" ?
                  <section className="space-y-5">
                    <SectionHeader
                      kicker="Overview"
                      title="Screening summary"
                    />
                    <ResearchScoreboard
                      matrix={screeningDetail?.confusion_matrix}
                      metrics={screeningDetail?.metrics ?? []}
                    />
                    <MetricGrid metrics={screeningDetail?.metrics ?? []} />
                    <div className="space-y-5">
                      <Suspense
                        fallback={<ChartSkeleton title="Research Flow" />}
                      >
                        <FunnelPanel
                          items={funnelItems}
                          matrix={screeningDetail?.confusion_matrix}
                        />
                      </Suspense>
                      <Suspense fallback={<ChartSkeleton title="Charts" />}>
                        <BarsPanel
                          decisionCounts={
                            screeningDetail?.decision_counts ?? []
                          }
                          stageCounts={screeningDetail?.stage_counts ?? []}
                          fulltextCounts={
                            screeningDetail?.fulltext_counts ?? []
                          }
                        />
                      </Suspense>
                    </div>
                  </section>
                : null}

                {screeningViewTab === "matrix" ?
                  <section className="space-y-5">
                    <SectionHeader
                      kicker="Confusion Matrix"
                      title="Prediction quality"
                    />
                    <ConfusionMatrixPanel
                      matrix={screeningDetail?.confusion_matrix}
                    />
                  </section>
                : null}

                {screeningViewTab === "failures" ?
                  <section className="space-y-5">
                    <SectionHeader
                      kicker="Failure Cases"
                      title="Missed GT and false positives"
                    />
                    <FailureCasesPanel
                      fnRows={failureRows.fn}
                      fpRows={failureRows.fp}
                    />
                  </section>
                : null}

                {screeningViewTab === "pool" ?
                  <section className="space-y-5">
                    <SectionHeader
                      kicker="Paper Pool"
                      title="Screened records"
                    />
                    <Card className="overflow-hidden">
                      <div className="flex flex-col gap-4 border-b border-sage-100 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
                        <div className="section-title">Paper Pool</div>
                        <div className="w-full lg:max-w-md">
                          <Input
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="Search PMID, title, decision, stage..."
                          />
                        </div>
                      </div>
                      <div className="p-5">
                        <PaperTable rows={filteredPapers} />
                      </div>
                    </Card>
                  </section>
                : null}

                {screeningViewTab === "provenance" ?
                  <section className="space-y-5">
                    <SectionHeader
                      kicker="Provenance"
                      title="Run artifacts"
                    />
                    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
                      <ProvenancePanel
                        run={screeningDetail?.run ?? {}}
                        title="Run Provenance"
                      />
                      <Card className="overflow-hidden p-5">
                        <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                          <FileBarChart2 className="h-4 w-4 text-sage-700" />
                          Screening Report Preview
                        </div>
                        <pre className="mt-4 max-h-[380px] overflow-auto bg-slate-950 px-4 py-4 font-mono text-xs leading-6 text-slate-100">
                          {screeningDetail?.report_preview ||
                            "No report preview available."}
                        </pre>
                      </Card>
                    </div>
                  </section>
                : null}
              </>
            : <>
                <SectionNav
                  activeId={extractionViewTab}
                  onSelect={(id) =>
                    setExtractionViewTab(id as ExtractionViewTab)
                  }
                  items={[
                    { id: "overview", label: "Overview" },
                    { id: "outputs", label: "Outputs" },
                    { id: "provenance", label: "Provenance" },
                  ]}
                />

                {extractionViewTab === "overview" ?
                  <section className="space-y-5">
                    <SectionHeader
                      kicker="Overview"
                      title="Extraction summary"
                    />
                    <MetricGrid metrics={extractionDetail?.metrics ?? []} />
                  </section>
                : null}

                {extractionViewTab === "outputs" ?
                  <section className="space-y-5">
                    <SectionHeader
                      kicker="Outputs"
                      title="Extraction outputs"
                    />
                    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
                      <Card className="overflow-hidden p-5">
                        <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                          <Microscope className="h-4 w-4 text-earth-600" />
                          Extraction Outputs
                        </div>
                        <div className="mt-4 space-y-3">
                          {(extractionDetail?.outputs ?? []).map(
                            (output, idx) => (
                              <div
                                key={`${output.path ?? idx}`}
                                className="border border-earth-100 bg-earth-50/70 p-4"
                              >
                                <div className="text-sm font-semibold text-slate-900">
                                  {String(output.path ?? "output")}
                                </div>
                                <div className="mt-2 text-xs leading-6 text-slate-600">
                                  {JSON.stringify(output, null, 2)}
                                </div>
                              </div>
                            ),
                          )}
                          {(extractionDetail?.outputs ?? []).length === 0 ?
                            <div className="border border-dashed border-earth-200 p-5 text-sm text-slate-500">
                              No output entries were recorded in the manifest.
                            </div>
                          : null}
                        </div>
                      </Card>
                      <Card className="overflow-hidden p-5">
                        <div className="section-title">Output Summary</div>
                        <div className="mt-2 text-sm leading-6 text-slate-600">
                          {(extractionDetail?.outputs ?? []).length} structured
                          output item(s) available for the current extraction
                          run.
                        </div>
                      </Card>
                    </div>
                  </section>
                : null}

                {extractionViewTab === "provenance" ?
                  <section className="space-y-5">
                    <SectionHeader
                      kicker="Provenance"
                      title="Runtime metadata"
                    />
                    <ProvenancePanel
                      run={extractionDetail?.run ?? {}}
                      title="Extraction Provenance"
                    />
                  </section>
                : null}
              </>
            }
          </main>
        </div>
      </div>
    </div>
  );
}

function Hero({
  moduleTab,
  onRefresh,
  loading,
  activeRun,
}: {
  moduleTab: ModuleTab;
  onRefresh: () => void;
  loading: boolean;
  activeRun: Record<string, unknown> | null;
}) {
  const title = deriveRunTitle(moduleTab, activeRun);
  const meta = deriveRunMeta(moduleTab, activeRun);

  return (
    <div className="bg-transparent px-1 py-1">
      <div className="flex flex-col gap-4 border-b border-sage-100/90 pb-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="editorial-kicker">
            {moduleTab === "screening" ?
              "Selected screening run"
            : "Selected extraction run"}
          </div>
          <h2 className="truncate text-[1.55rem] font-semibold tracking-tight text-slate-950 lg:text-[1.9rem]">
            {title}
          </h2>
          {meta.length ?
            <div className="flex flex-wrap gap-x-4 gap-y-2 pt-1 text-sm">
              {meta.map((item) => (
                <div
                  key={item.label}
                  className="flex items-baseline gap-2"
                >
                  <span className="text-slate-400">{item.label}</span>
                  <span className="font-medium text-slate-800">
                    {item.value}
                  </span>
                </div>
              ))}
            </div>
          : null}
        </div>
        <div className="flex items-center gap-3">
          <div className="inline-flex items-center bg-sage-50/85 px-3 py-2 text-xs uppercase tracking-[0.18em] text-slate-500">
            Active
            <span className="ml-2 text-slate-900">
              {moduleTab === "screening" ? "Screening" : "Extraction"}
            </span>
          </div>
          <Button
            onClick={onRefresh}
            disabled={loading}
            className="px-3 py-2 text-sm"
          >
            <RefreshCw
              className={cn("mr-2 h-4 w-4", loading && "animate-spin")}
            />
            Refresh
          </Button>
        </div>
      </div>
    </div>
  );
}

function SectionNav({
  items,
  activeId,
  onSelect,
}: {
  items: Array<{ id: string; label: string }>;
  activeId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2 border-b border-sage-100 pb-3">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => onSelect(item.id)}
          className={cn(
            "px-4 py-2 text-sm font-semibold transition",
            activeId === item.id ?
              "bg-sage-700 text-white"
            : "bg-sage-50/80 text-slate-700 hover:bg-sage-100",
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

function SectionHeader({
  kicker,
  title,
  description,
}: {
  kicker: string;
  title: string;
  description?: string;
}) {
  return (
    <div className="space-y-1">
      <div className="editorial-kicker">{kicker}</div>
      <div className="text-[1.15rem] font-semibold tracking-tight text-slate-950">
        {title}
      </div>
      {description ? (
        <div className="max-w-3xl text-sm leading-6 text-slate-600">
          {description}
        </div>
      ) : null}
    </div>
  );
}

function MetricGrid({
  metrics,
}: {
  metrics: Array<{ label: string; value: number }>;
}) {
  if (metrics.length === 0) {
    return (
      <Card className="p-5 text-sm text-slate-500">
        No metrics recorded for this run yet.
      </Card>
    );
  }
  return (
    <Card className="overflow-hidden">
      <div className="border-b border-sage-100 px-5 py-4">
        <div className="section-title">Run Metrics</div>
        <div className="mt-1 text-xs text-slate-500">
          Primary counts extracted from the current run output.
        </div>
      </div>
      <div className="grid divide-y divide-sage-100 sm:grid-cols-2 sm:divide-x sm:divide-y-0 2xl:grid-cols-3">
        {metrics.map((metric) => (
          <div
            key={metric.label}
            className="px-5 py-4"
          >
            <div className="editorial-kicker">{metric.label}</div>
            <div className="mt-3 font-mono text-[2rem] font-semibold tracking-tight text-slate-950">
              {metric.value}
            </div>
            <div className="mt-2 h-px w-10 bg-sage-200" />
          </div>
        ))}
      </div>
    </Card>
  );
}

function ResearchScoreboard({
  matrix,
  metrics,
}: {
  matrix?: ConfusionMatrix | null;
  metrics: Array<{ label: string; value: number }>;
}) {
  if (!matrix) {
    return null;
  }

  const pool = metrics.find((item) => item.label === "Pool")?.value ?? 0;
  const predictedRelevant = matrix.tp + matrix.fp;
  const workloadReduction = pool > 0 ? 1 - predictedRelevant / pool : 0;
  const nns = matrix.tp > 0 ? predictedRelevant / matrix.tp : 0;

  const boardItems = [
    {
      label: "Recall",
      value: `${(matrix.recall * 100).toFixed(1)}%`,
      progress: matrix.recall,
      tone: "sage" as const,
      caption: "GT papers recovered as relevant.",
    },
    {
      label: "Workload Reduction",
      value: `${(workloadReduction * 100).toFixed(1)}%`,
      progress: workloadReduction,
      tone: "sky" as const,
      caption: "Pool excluded from downstream review.",
    },
    {
      label: "NNS",
      value: nns > 0 ? nns.toFixed(2) : "0.00",
      progress: nns > 0 ? Math.max(0, Math.min(1, 1 / nns)) : 0,
      tone: "rose" as const,
      caption: "Papers needed to screen per true GT hit.",
    },
    {
      label: "Precision",
      value: `${(matrix.precision * 100).toFixed(1)}%`,
      progress: matrix.precision,
      tone: "earth" as const,
      caption: "Relevant predictions that are truly GT.",
    },
  ];

  return (
    <Card className="overflow-hidden p-5">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="section-title">Research Efficiency Board</div>
          <div className="mt-1 text-xs text-slate-500">
            Compact readout for retrieval quality, downstream burden, and
            screening efficiency.
          </div>
        </div>
        <div className="text-xs text-slate-500">
          Predicted relevant = TP + FP
        </div>
      </div>
      <div className="mt-5 grid divide-y divide-sage-100 bg-sage-50/35 xl:grid-cols-4 xl:divide-x xl:divide-y-0">
        {boardItems.map((item) => (
          <EfficiencyCard
            key={item.label}
            {...item}
          />
        ))}
      </div>
    </Card>
  );
}

function EfficiencyCard({
  label,
  value,
  progress,
  tone,
  caption,
}: {
  label: string;
  value: string;
  progress: number;
  tone: "sage" | "earth" | "sky" | "rose";
  caption: string;
}) {
  const toneMap = {
    sage: {
      chip: "bg-sage-50 text-sage-800",
      bar: "bg-sage-600",
      rail: "bg-sage-100",
    },
    earth: {
      chip: "bg-slate-100 text-slate-800",
      bar: "bg-slate-500",
      rail: "bg-slate-100",
    },
    sky: {
      chip: "bg-[#e7eff1] text-[#486672]",
      bar: "bg-[#5f8290]",
      rail: "bg-[#dbe7ea]",
    },
    rose: {
      chip: "bg-[#f2ecea] text-[#7a635f]",
      bar: "bg-[#8f746f]",
      rail: "bg-[#efe5e2]",
    },
  } as const;

  const config = toneMap[tone];

  return (
    <div className="px-4 py-4">
      <div
        className={cn(
          "inline-flex rounded-sm px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]",
          config.chip,
        )}
      >
        {label}
      </div>
      <div className="mt-4 font-mono text-3xl font-semibold tracking-tight text-slate-950">
        {value}
      </div>
      <div className="mt-3 h-2 bg-slate-100">
        <div
          className={cn("h-2 transition-all", config.bar)}
          style={{ width: `${Math.max(0, Math.min(100, progress * 100))}%` }}
        />
      </div>
      <div className="mt-3 text-sm leading-6 text-slate-600">{caption}</div>
    </div>
  );
}

function ChartSkeleton({ title }: { title: string }) {
  return (
    <div className="bg-sage-50/35 p-4">
      <div className="mb-3 section-title">{title}</div>
      <div className="h-[240px] animate-pulse bg-white/70" />
    </div>
  );
}

function ProvenancePanel({
  run,
  title,
}: {
  run: Record<string, unknown>;
  title: string;
}) {
  const entries = Object.entries(run).filter(
    ([, value]) => value !== null && value !== undefined,
  );
  return (
    <Card className="overflow-hidden p-5">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <ShieldCheck className="h-4 w-4 text-sage-700" />
        {title}
      </div>
      <div className="mt-4 bg-sage-50/30">
        {entries.map(([key, value]) => (
          <MetaBlock
            key={key}
            label={key}
            value={value}
          />
        ))}
        {entries.length === 0 ?
          <div className="p-5 text-sm text-slate-500">
            No provenance payload available.
          </div>
        : null}
      </div>
    </Card>
  );
}

function ConfusionMatrixPanel({ matrix }: { matrix?: ConfusionMatrix | null }) {
  if (!matrix) {
    return (
      <Card className="p-5 text-sm text-slate-500">
        No confusion-matrix data available for this run.
      </Card>
    );
  }

  const cells = [
    {
      label: "TP",
      value: matrix.tp,
      tone: "bg-sage-100 text-sage-900 border-sage-200",
      subtitle: "Predicted relevant & GT",
    },
    {
      label: "FP",
      value: matrix.fp,
      tone: "bg-earth-100 text-earth-900 border-earth-200",
      subtitle: "Predicted relevant & non-GT",
    },
    {
      label: "FN",
      value: matrix.fn,
      tone: "bg-rose-100 text-rose-900 border-rose-200",
      subtitle: "Missed GT",
    },
    {
      label: "TN",
      value: matrix.tn,
      tone: "bg-sky-100 text-sky-900 border-sky-200",
      subtitle: "Predicted non-relevant & non-GT",
    },
  ];

  const summaryMetrics = [
    { label: "Recall", value: matrix.recall },
    { label: "Precision", value: matrix.precision },
    { label: "Specificity", value: matrix.specificity },
    { label: "Accuracy", value: matrix.accuracy },
  ];

  return (
    <Card className="overflow-hidden p-5">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-900">
            Confusion Matrix
          </div>
          <div className="mt-1 text-xs text-slate-500">
            Relevant prediction is defined as{" "}
            <span className="font-semibold">Strong + Possible</span>.
          </div>
        </div>
        <div className="text-xs text-slate-500">
          Actual positive = Ground Truth in pool
        </div>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_340px]">
        <div>
          <div className="mb-3 grid grid-cols-[110px_1fr_1fr] gap-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            <div />
            <div>Actual GT</div>
            <div>Actual non-GT</div>
          </div>
          <div className="grid grid-cols-[110px_1fr_1fr] gap-3">
            <div className="flex items-center justify-center border border-sage-100 bg-sage-50/60 px-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Pred. rel
            </div>
            <MatrixCell {...cells[0]} />
            <MatrixCell {...cells[1]} />
            <div className="flex items-center justify-center border border-sage-100 bg-sage-50/60 px-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Pred. non-rel
            </div>
            <MatrixCell {...cells[2]} />
            <MatrixCell {...cells[3]} />
          </div>
        </div>

        <div className="grid divide-y divide-sage-100 border border-sage-100/90 bg-white/82">
          {summaryMetrics.map((item) => (
            <div
              key={item.label}
              className="px-4 py-4"
            >
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                {item.label}
              </div>
              <div className="mt-2 font-mono text-3xl font-semibold text-slate-950">
                {(item.value * 100).toFixed(1)}%
              </div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

function FailureCasesPanel({
  fnRows,
  fpRows,
}: {
  fnRows: Array<Record<string, string | number | boolean | null>>;
  fpRows: Array<Record<string, string | number | boolean | null>>;
}) {
  return (
    <Card className="overflow-hidden">
      <div className="grid xl:grid-cols-2 xl:divide-x xl:divide-sage-100">
        <FailureListCard
          title="False Negatives"
          subtitle="Ground-truth papers not promoted to Strong/Possible."
          tone="rose"
          rows={fnRows}
        />
        <FailureListCard
          title="High-score False Positives"
          subtitle="Non-GT papers promoted as relevant, sorted by overall score."
          tone="earth"
          rows={fpRows.slice(0, 20)}
        />
      </div>
    </Card>
  );
}

function FailureListCard({
  title,
  subtitle,
  rows,
  tone,
}: {
  title: string;
  subtitle: string;
  rows: Array<Record<string, string | number | boolean | null>>;
  tone: "rose" | "earth";
}) {
  const toneClass = tone === "rose" ? "bg-rose-50/35" : "bg-earth-50/35";
  return (
    <div>
      <div className="border-b border-sage-100 px-5 py-4">
        <div className="section-title">{title}</div>
        <div className="mt-1 text-xs text-slate-500">{subtitle}</div>
      </div>
      <div className="divide-y divide-sage-100">
        {rows.length === 0 ?
          <div className="px-5 py-5 text-sm text-slate-500">
            No rows in this category for the current run.
          </div>
        : null}
        {rows.map((row, index) => (
          <div
            key={`${row.PMID ?? index}`}
            className={cn("px-5 py-4", toneClass)}
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={tone === "rose" ? "rose" : "amber"}>
                PMID {String(row.PMID ?? "-")}
              </Badge>
              {row.llm_suggest ?
                <Badge tone="stone">{String(row.llm_suggest)}</Badge>
              : null}
              {(
                row.overall_score !== undefined &&
                row.overall_score !== null &&
                row.overall_score !== ""
              ) ?
                <Badge tone="blue">score {String(row.overall_score)}</Badge>
              : null}
            </div>
            <div className="mt-3 text-sm font-semibold leading-6 text-slate-900">
              {String(row.Title ?? "-")}
            </div>
            <div className="mt-2 text-sm leading-6 text-slate-600">
              {String(row.screening_stage ?? "-")}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MatrixCell({
  label,
  value,
  subtitle,
  tone,
}: {
  label: string;
  value: number;
  subtitle: string;
  tone: string;
}) {
  return (
    <div className={cn("border p-5", tone)}>
      <div className="text-xs font-semibold uppercase tracking-[0.18em] opacity-75">
        {label}
      </div>
      <div className="mt-2 font-mono text-4xl font-semibold">{value}</div>
      <div className="mt-2 text-sm leading-6 opacity-80">{subtitle}</div>
    </div>
  );
}

function isGroundTruth(row: Record<string, string | number | boolean | null>) {
  const value = String(row.is_ground_truth ?? row.ground_truth ?? row.gt ?? "")
    .trim()
    .toLowerCase();
  return ["✓", "gt", "true", "1", "yes", "y"].includes(value);
}

function isPredictedRelevant(
  row: Record<string, string | number | boolean | null>,
) {
  const value = String(row.llm_suggest ?? "")
    .trim()
    .toLowerCase();
  return value.includes("strong") || value.includes("possible");
}

function deriveRunTitle(
  moduleTab: ModuleTab,
  run: Record<string, unknown> | null,
) {
  if (!run) {
    return moduleTab === "screening" ? "Screening overview" : (
        "Extraction overview"
      );
  }
  const project = deriveProjectName(run);
  return String(
    run.config ||
      project ||
      run.topic ||
      run.stage ||
      run.workflow ||
      "Selected run",
  );
}

function deriveRunMeta(
  moduleTab: ModuleTab,
  run: Record<string, unknown> | null,
) {
  if (!run) {
    return [];
  }
  const items: Array<{ label: string; value: string }> = [];
  const project = deriveProjectName(run);
  const topic = toText(run.topic);
  const config = toText(run.config);
  const stage = toText(run.stage);
  const timestamp = formatTimestamp(run.timestamp_utc);

  if (project) items.push({ label: "Project", value: project });
  if (topic) items.push({ label: "Parameter", value: topic });
  if (config) items.push({ label: "Config", value: config });
  if (moduleTab === "extraction" && stage)
    items.push({ label: "Stage", value: stage });
  if (timestamp) items.push({ label: "Timestamp", value: timestamp });
  return items;
}

function deriveProjectName(run: Record<string, unknown>) {
  const candidates = [run.screened_csv, run.manifest_path, run.label]
    .map((value) => toText(value))
    .filter(Boolean) as string[];

  for (const candidate of candidates) {
    const normalized = candidate.replace(/\\/g, "/");
    const filename = normalized.split("/").pop() ?? normalized;
    const match = filename.match(/project[_-]?\d+/i);
    if (match) {
      return match[0].replace(/_/g, " ").replace(/\bproject\b/i, "Project");
    }
    if (filename) {
      return filename;
    }
  }
  return "";
}

function formatTimestamp(value: unknown) {
  const text = toText(value);
  if (!text) {
    return "";
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  return parsed.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toText(value: unknown) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

function MetaBlock({ label, value }: { label: string; value: unknown }) {
  const rendered =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div className="border-t border-sage-100 px-4 py-4 first:border-t-0">
      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
        {label}
      </div>
      <div className="mt-2 whitespace-pre-wrap break-all text-sm leading-6 text-slate-700">
        {rendered}
      </div>
    </div>
  );
}
