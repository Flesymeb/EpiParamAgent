import type {
  ExtractionRunDetail,
  RunSummary,
  ScreeningPapersResponse,
  ScreeningRunDetail,
  SummaryResponse,
} from "@/types";

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8008/api";
const DEFAULT_ROOT = import.meta.env.VITE_WORKBENCH_ROOT ?? "";

function withRoot(path: string) {
  const url = new URL(`${API_BASE}${path}`);
  if (DEFAULT_ROOT) {
    url.searchParams.set("root", DEFAULT_ROOT);
  }
  return url.toString();
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  summary: () => getJson<SummaryResponse>(withRoot("/summary")),
  screeningRuns: async () =>
    (await getJson<{ items: RunSummary[] }>(withRoot("/screening/runs"))).items,
  screeningRun: (runId: string) =>
    getJson<ScreeningRunDetail>(withRoot(`/screening/runs/${runId}`)),
  screeningRunPapers: (runId: string) =>
    getJson<ScreeningPapersResponse>(withRoot(`/screening/runs/${runId}/papers`)),
  extractionRuns: async () =>
    (await getJson<{ items: RunSummary[] }>(withRoot("/extraction/runs"))).items,
  extractionRun: (runId: string) =>
    getJson<ExtractionRunDetail>(withRoot(`/extraction/runs/${runId}`)),
};
