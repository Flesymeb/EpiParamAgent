import {
  BarChart3Icon,
  BracesIcon,
  DownloadIcon,
  FilterIcon,
  SearchIcon,
  TableIcon,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

export type PipelineStepId =
  | "query"
  | "retrieve"
  | "screen"
  | "code"
  | "extract"
  | "analyze"

export type CodingStage = "index" | "extract"

export type PipelineStep = {
  id: PipelineStepId
  /** UI position 1..6 (display only). */
  number: number
  /** The backend step_no this UI stage drives + reads status from. */
  backendStep: number
  /** For the two coding-derived stages, which coding sub-stage it surfaces. */
  codingStage?: CodingStage
  label: string
  title: string
  description: string
  icon: LucideIcon
}

// Six UI stages over five backend steps: Code + Extraction both map to backend
// step 4 (one coding run produces the index result and the coding sheet); the
// UI splits them into two visible panels. Analysis = backend step 5 (pooling).
export const PIPELINE_STEPS: readonly PipelineStep[] = [
  {
    id: "query",
    number: 1,
    backendStep: 1,
    label: "Query",
    title: "Query Builder",
    description: "Keyword generation and Boolean query setup.",
    icon: SearchIcon,
  },
  {
    id: "retrieve",
    number: 2,
    backendStep: 2,
    label: "Retrieval",
    title: "Evidence Retrieval",
    description: "Candidate records and source collection.",
    icon: DownloadIcon,
  },
  {
    id: "screen",
    number: 3,
    backendStep: 3,
    label: "Screen",
    title: "Eligibility Screening",
    description: "Inclusion, exclusion, and review decisions.",
    icon: FilterIcon,
  },
  {
    id: "code",
    number: 4,
    backendStep: 4,
    codingStage: "index",
    label: "Code",
    title: "Structured Indexing",
    description: "Per-paper structured index of where evidence lives.",
    icon: BracesIcon,
  },
  {
    id: "extract",
    number: 5,
    backendStep: 4,
    codingStage: "extract",
    label: "Extraction",
    title: "Data Extraction",
    description: "Codebook-driven value extraction into a coding sheet.",
    icon: TableIcon,
  },
  {
    id: "analyze",
    number: 6,
    backendStep: 5,
    label: "Analysis",
    title: "Meta-Analysis",
    description: "Effect pooling and synthesis outputs.",
    icon: BarChart3Icon,
  },
]

const PIPELINE_STEP_ALIASES: Readonly<Record<string, PipelineStepId>> = {
  analysis: "analyze",
  coding: "code",
  extraction: "extract",
  meta: "analyze",
  metaanalysis: "analyze",
  pooling: "analyze",
  pool: "analyze",
  retrieval: "retrieve",
  screening: "screen",
}

export function resolvePipelineStepId(value: string | null): PipelineStepId {
  const normalizedValue = value?.trim().toLowerCase().replace(/[^a-z0-9]/g, "")

  if (!normalizedValue) {
    return PIPELINE_STEPS[0].id
  }

  return (
    PIPELINE_STEPS.find((step) => step.id === normalizedValue)?.id ??
    PIPELINE_STEP_ALIASES[normalizedValue] ??
    PIPELINE_STEPS[0].id
  )
}

export function getPipelineStep(id: PipelineStepId): PipelineStep {
  return PIPELINE_STEPS.find((step) => step.id === id) ?? PIPELINE_STEPS[0]
}
