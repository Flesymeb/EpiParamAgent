// Per-step input field schema for the pipeline configuration forms.
//
// Field keys map 1:1 to the params each backend step reads (see webapp/app/steps/*).
// Stages are the 6 UI stages (see lib/pipeline.ts); Code (4) and Extraction (5)
// both drive backend coding (step 4). `group` clusters fields into titled
// sub-stage sections; `advanced` fields collapse under an Advanced disclosure.

export type StepFieldType =
  | "text"
  | "number"
  | "textarea"
  | "select"
  | "switch"
  | "year_range"
  | "tags"

export type StepFieldOption = { value: string; label: string }

export type StepField = {
  key: string
  label: string
  type: StepFieldType
  /** Titled sub-stage section this field belongs to. */
  group?: string
  placeholder?: string
  helperText?: string
  options?: StepFieldOption[]
  /** Clickable suggested values for a `tags` field. */
  suggestions?: string[]
  defaultValue?: string
  /** Hidden behind the "Advanced" disclosure. */
  advanced?: boolean
  min?: number
  max?: number
  step?: number
}

export type StepConfig = {
  stepNumber: number
  /** One-line summary shown above the fields, MetaScreener-style guidance. */
  blurb: string
  fields: StepField[]
}

const PARAMETER_OPTIONS: StepFieldOption[] = [
  { value: "serial_interval", label: "Serial interval" },
  { value: "reproduction_number", label: "Reproduction number (R/R0)" },
  { value: "fatality", label: "Case fatality (CFR)" },
]

const LLM_FIELDS: StepField[] = [
  {
    key: "model",
    label: "Model",
    type: "text",
    group: "Model",
    placeholder: "server default (e.g. z-ai/glm-5.1)",
    helperText: "OpenRouter model id. Blank uses the server default.",
    advanced: true,
  },
  {
    key: "provider",
    label: "Provider",
    type: "text",
    group: "Model",
    placeholder: "server default",
    helperText: "LLM provider override. Blank uses the server default.",
    advanced: true,
  },
  {
    key: "temperature",
    label: "Temperature",
    type: "number",
    group: "Model",
    placeholder: "0",
    helperText: "0 = deterministic. Higher = more varied phrasing.",
    min: 0,
    max: 2,
    step: 0.1,
    advanced: true,
  },
]

export const STEP_CONFIGS: Record<number, StepConfig> = {
  1: {
    stepNumber: 1,
    blurb:
      "Describe the review question and seed terms. The LLM expands them into a structured Boolean query you can edit before searching.",
    fields: [
      {
        key: "keywords",
        label: "Seed keywords",
        type: "tags",
        group: "Research question",
        placeholder: "Type a term, press Enter…",
        helperText:
          "Seed terms the model expands into a Boolean query. Add your own or pick suggestions.",
        suggestions: [
          "serial interval",
          "generation interval",
          "incubation period",
          "reproduction number",
          "case fatality",
          "household transmission",
          "transmission pairs",
          "contact tracing",
          "outbreak",
        ],
      },
      {
        key: "research_question",
        label: "Research question",
        type: "textarea",
        group: "Research question",
        placeholder:
          "Among confirmed mpox cases in the 2022 outbreak, what is the serial interval?",
        helperText:
          "Plain-language question. PICO-style phrasing helps the model.",
      },
      {
        key: "disease",
        label: "Disease / condition",
        type: "text",
        group: "Research question",
        placeholder: "mpox",
        helperText: "Used to route datasets and codebooks (e.g. mpox, covid19).",
      },
      {
        key: "parameter",
        label: "Target parameter",
        type: "select",
        group: "Research question",
        options: PARAMETER_OPTIONS,
        defaultValue: "serial_interval",
        helperText: "Epidemiological parameter to extract and pool downstream.",
      },
      {
        key: "date_range",
        label: "Publication years",
        type: "year_range",
        group: "Search scope",
        placeholder: "Any",
        helperText:
          "Restrict the PubMed search to a publication-year range (applied during retrieval).",
      },
      {
        key: "retmax",
        label: "Max records",
        type: "number",
        group: "Search scope",
        placeholder: "200",
        defaultValue: "200",
        helperText:
          "Maximum PubMed records to fetch during retrieval. Blank = all matches.",
        min: 1,
      },
      ...LLM_FIELDS,
    ],
  },
  2: {
    stepNumber: 2,
    blurb:
      "Search PubMed with the generated query. Leave the query blank to use the Query stage output, or paste your own Boolean string to override it. Year range and max records are set on the Query stage.",
    fields: [
      {
        key: "query",
        label: "Boolean query (override)",
        type: "textarea",
        group: "Search",
        placeholder:
          "(mpox OR monkeypox) AND (serial interval OR generation time)",
        helperText:
          "Defaults to the Query stage's query.json. Edit here to override for this search.",
      },
    ],
  },
  3: {
    stepNumber: 3,
    blurb:
      "The LLM screens each title/abstract for eligibility against the inclusion criteria. Tune batch size and decision strategy as needed.",
    fields: [
      {
        key: "research_question",
        label: "Inclusion criteria",
        type: "textarea",
        group: "Eligibility",
        placeholder:
          "Include studies reporting an empirical serial interval estimate for mpox.",
        helperText:
          "The eligibility rule each title/abstract is judged against. State what makes a study includable. Inherited from the Query stage if left blank.",
      },
      {
        key: "batch_size",
        label: "Batch size",
        type: "number",
        group: "Batch & strategy",
        placeholder: "20",
        defaultValue: "20",
        helperText: "Abstracts sent to the model per batch.",
        min: 1,
        max: 100,
      },
      {
        key: "strategy",
        label: "Decision strategy",
        type: "text",
        group: "Batch & strategy",
        placeholder: "binary",
        defaultValue: "binary",
        helperText:
          "Screening prompt strategy. Default: binary (include / exclude).",
        advanced: true,
      },
      ...LLM_FIELDS,
    ],
  },
  4: {
    stepNumber: 4,
    blurb:
      "Fetch full texts and build a per-paper structured index. Choose where PDFs come from and which codebook drives indexing.",
    fields: [
      {
        key: "parameter",
        label: "Target parameter",
        type: "select",
        group: "Source",
        options: PARAMETER_OPTIONS,
        defaultValue: "serial_interval",
        helperText: "Selects the codebook used for extraction.",
      },
      {
        key: "disease",
        label: "Disease / condition",
        type: "text",
        group: "Source",
        placeholder: "covid19",
        defaultValue: "covid19",
        helperText: "Routes to dataset/codebook directories.",
      },
      {
        key: "fetch_strategy",
        label: "Full-text source",
        type: "select",
        group: "Indexing & fetch",
        options: [
          { value: "pmc_only", label: "PMC only (open access)" },
          {
            value: "pmc_scihub_manual",
            label: "PMC + Sci-Hub + manual fallback",
          },
        ],
        defaultValue: "pmc_only",
        helperText: "Where to source full-text PDFs.",
      },
      {
        key: "stage",
        label: "Pipeline stage",
        type: "select",
        group: "Indexing & fetch",
        options: [
          { value: "fetch", label: "Fetch — download PDFs only" },
          { value: "index", label: "Index — parse fetched PDFs" },
          { value: "extract", label: "Extract — LLM coding (runs fetch+index)" },
          { value: "both", label: "Both — index + extract" },
        ],
        defaultValue: "both",
        helperText:
          "How far to run the coding pipeline. Both produces the structured index and the coding sheet in one pass.",
      },
      {
        key: "profile",
        label: "Profile / topic",
        type: "text",
        group: "Codebook",
        placeholder: "dataset profile id",
        helperText:
          "Coding project profile (dataset subfolder). Required by the dataset layout.",
        advanced: true,
      },
      {
        key: "codebook_path",
        label: "Codebook path (override)",
        type: "text",
        group: "Codebook",
        placeholder: "configs/<disease>/codebooks/<parameter>.yaml",
        helperText: "Defaults to the disease + parameter codebook.",
        advanced: true,
      },
    ],
  },
  5: {
    stepNumber: 5,
    blurb:
      "Extraction runs as part of the Code stage (one coding pass produces both the structured index and this coding sheet). Review and edit the extracted values below before pooling.",
    fields: [],
  },
  6: {
    stepNumber: 6,
    blurb:
      "Pool the coded estimates into a meta-analytic summary. Pick the effect model and effect measure; toggle transforms for skewed parameters.",
    fields: [
      {
        key: "method",
        label: "Effect model",
        type: "select",
        group: "Effect model",
        options: [
          { value: "random", label: "Random effects" },
          { value: "fixed", label: "Fixed effect" },
        ],
        defaultValue: "random",
        helperText:
          "Random effects allows between-study heterogeneity (usually preferred).",
      },
      {
        key: "estimate_measure",
        label: "Effect measure",
        type: "select",
        group: "Effect model",
        options: [
          { value: "mean", label: "Mean" },
          { value: "median", label: "Median" },
        ],
        defaultValue: "mean",
        helperText: "Which point estimate rows to pool.",
      },
      {
        key: "group_by",
        label: "Subgroup by",
        type: "text",
        group: "Subgroups & filters",
        placeholder: "disease_name",
        helperText:
          "Optional column to produce subgroup estimates. Blank = pool all.",
      },
      {
        key: "parameter_type",
        label: "Parameter type filter",
        type: "text",
        group: "Subgroups & filters",
        placeholder: "serial_interval",
        helperText:
          "Filter coded rows by parameter_type. Inherited from the Query stage if blank.",
        advanced: true,
      },
      {
        key: "log_transform",
        label: "Log-transform before pooling",
        type: "switch",
        group: "Transforms",
        helperText:
          "Pool log(estimate) then back-transform. Use for skewed/positive parameters.",
        advanced: true,
      },
      {
        key: "include_median",
        label: "Include median rows",
        type: "switch",
        group: "Transforms",
        helperText: "Treat median rows as means (mean measure only).",
        advanced: true,
      },
      {
        key: "impute_missing_se",
        label: "Impute missing SE",
        type: "switch",
        group: "Transforms",
        defaultValue: "true",
        helperText:
          "Use a conservative SE for rows lacking CI/SD/SE (on by default).",
        advanced: true,
      },
    ],
  },
}

export function getStepConfig(stepNumber: number): StepConfig | undefined {
  return STEP_CONFIGS[stepNumber]
}
