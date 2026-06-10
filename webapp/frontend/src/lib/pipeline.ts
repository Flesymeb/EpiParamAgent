export const PIPELINE_STEPS = [
  {
    id: "query",
    number: 1,
    label: "Query",
    title: "Query Builder",
    description: "Protocol question and search seed setup.",
  },
  {
    id: "retrieve",
    number: 2,
    label: "Retrieve",
    title: "Evidence Retrieval",
    description: "Candidate records and source collection.",
  },
  {
    id: "screen",
    number: 3,
    label: "Screen",
    title: "Eligibility Screening",
    description: "Inclusion, exclusion, and review decisions.",
  },
  {
    id: "code",
    number: 4,
    label: "Code",
    title: "Data Coding",
    description: "Structured extraction and adjudication.",
  },
  {
    id: "pool",
    number: 5,
    label: "Pool",
    title: "Meta-Analysis Pooling",
    description: "Effect pooling and synthesis outputs.",
  },
] as const

export type PipelineStep = (typeof PIPELINE_STEPS)[number]
export type PipelineStepId = PipelineStep["id"]

export function resolvePipelineStepId(value: string | null): PipelineStepId {
  return (
    PIPELINE_STEPS.find((step) => step.id === value)?.id ??
    PIPELINE_STEPS[0].id
  )
}

export function getPipelineStep(id: PipelineStepId): PipelineStep {
  return PIPELINE_STEPS.find((step) => step.id === id) ?? PIPELINE_STEPS[0]
}
