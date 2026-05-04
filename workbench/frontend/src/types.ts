export type RunSummary = {
  id: string;
  label: string;
  module: string;
  topic?: string | null;
  config?: string | null;
  timestamp_utc?: string | null;
  status: string;
  screened_csv?: string | null;
  manifest_path?: string | null;
};

export type CountItem = {
  label: string;
  count: number;
};

export type ConfusionMatrix = {
  tp: number;
  fp: number;
  fn: number;
  tn: number;
  recall: number;
  precision: number;
  specificity: number;
  accuracy: number;
};

export type MetricSummary = {
  label: string;
  value: number;
};

export type ScreeningRunDetail = {
  run: Record<string, unknown>;
  metrics: MetricSummary[];
  decision_counts: CountItem[];
  stage_counts: CountItem[];
  fulltext_counts: CountItem[];
  confusion_matrix: ConfusionMatrix;
  report_preview: string;
};

export type ScreeningPapersResponse = {
  run_id: string;
  count: number;
  papers: Array<Record<string, string | number | boolean | null>>;
};

export type ExtractionRunDetail = {
  run: Record<string, unknown>;
  metrics: MetricSummary[];
  outputs: Array<Record<string, unknown>>;
};

export type SummaryResponse = {
  screening_runs: number;
  extraction_runs: number;
};
