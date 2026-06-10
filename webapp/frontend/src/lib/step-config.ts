// Per-step input field schema for the pipeline configuration forms.
//
// Field keys map 1:1 to the params each backend step reads (see webapp/app/steps/*).
// Defaults and select options are grounded in the real backend defaults so the
// forms never offer values the pipeline can't honor. Helper text is written for
// an epidemiology reviewer, explaining what each field does.

export type StepFieldType = "text" | "number" | "textarea" | "select" | "switch"

export type StepFieldOption = { value: string; label: string }

export type StepField = {
  key: string
  label: string
  type: StepFieldType
  placeholder?: string
  helperText?: string
  options?: StepFieldOption[]
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

export const STEP_CONFIGS: Record<number, StepConfig> = {
  1: {
    stepNumber: 1,
    blurb:
      "Describe the review question and seed terms. The LLM expands them into a structured Boolean query you can edit before searching.",
    fields: [
      {
        key: "keywords",
        label: "Seed keywords",
        type: "text",
        placeholder: "mpox serial interval incubation",
        helperText:
          "Free-text seed terms the model expands into a Boolean query.",
      },
      {
        key: "research_question",
        label: "Research question",
        type: "textarea",
        placeholder:
          "Among confirmed mpox cases in the 2022 outbreak, what is the serial interval?",
        helperText: "Plain-language question. PICO-style phrasing helps the model.",
      },
      {
        key: "disease",
        label: "Disease / condition",
        type: "text",
        placeholder: "mpox",
        helperText: "Used to route datasets and codebooks (e.g. mpox, covid19).",
      },
      {
        key: "parameter",
        label: "Target parameter",
        type: "select",
        options: PARAMETER_OPTIONS,
        defaultValue: "serial_interval",
        helperText: "Epidemiological parameter to extract and pool downstream.",
      },
      {
        key: "model",
        label: "Model",
        type: "text",
        placeholder: "server default (e.g. z-ai/glm-5.1)",
        helperText: "OpenRouter model id. Blank uses the server default.",
        advanced: true,
      },
      {
        key: "provider",
        label: "Provider",
        type: "text",
        placeholder: "server default",
        helperText: "LLM provider override. Blank uses the server default.",
        advanced: true,
      },
      {
        key: "temperature",
        label: "Temperature",
        type: "number",
        placeholder: "0",
        helperText: "0 = deterministic. Higher = more varied phrasing.",
        min: 0,
        max: 2,
        step: 0.1,
        advanced: true,
      },
    ],
  },
  2: {
    stepNumber: 2,
    blurb:
      "Search PubMed with the generated query. Leave the query blank to use Step 1's output, or paste your own Boolean string to override it.",
    fields: [
      {
        key: "query",
        label: "Boolean query (override)",
        type: "textarea",
        placeholder: "(mpox OR monkeypox) AND (serial interval OR generation time)",
        helperText:
          "Defaults to Step 1's query.json. Edit here to override for this search.",
      },
      {
        key: "retmax",
        label: "Max records",
        type: "number",
        placeholder: "200",
        defaultValue: "200",
        helperText: "Maximum PubMed records to fetch. Blank = fetch all matches.",
        min: 1,
      },
      {
        key: "date_range",
        label: "Publication years",
        type: "text",
        placeholder: "2022:2024",
        helperText: "PubMed year range (YYYY:YYYY). Optional.",
      },
    ],
  },
  3: {
    stepNumber: 3,
    blurb:
      "The LLM screens each title/abstract for eligibility against the research question. Tune batch size and decision strategy as needed.",
    fields: [
      {
        key: "research_question",
        label: "Inclusion question",
        type: "textarea",
        placeholder:
          "Include studies reporting an empirical serial interval estimate for mpox.",
        helperText:
          "Eligibility criterion each abstract is judged against. Inherited from Step 1 if blank.",
      },
      {
        key: "batch_size",
        label: "Batch size",
        type: "number",
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
        placeholder: "binary",
        defaultValue: "binary",
        helperText: "Screening prompt strategy. Default: binary (include / exclude).",
        advanced: true,
      },
      {
        key: "model",
        label: "Model",
        type: "text",
        placeholder: "server default",
        helperText: "OpenRouter model id override.",
        advanced: true,
      },
      {
        key: "provider",
        label: "Provider",
        type: "text",
        placeholder: "server default",
        helperText: "LLM provider override.",
        advanced: true,
      },
      {
        key: "temperature",
        label: "Temperature",
        type: "number",
        placeholder: "0",
        helperText: "0 = deterministic screening decisions.",
        min: 0,
        max: 2,
        step: 0.1,
        advanced: true,
      },
    ],
  },
  4: {
    stepNumber: 4,
    blurb:
      "Fetch full texts and run structured coding against the codebook. Choose how far to run the pipeline and where PDFs come from.",
    fields: [
      {
        key: "parameter",
        label: "Target parameter",
        type: "select",
        options: PARAMETER_OPTIONS,
        defaultValue: "serial_interval",
        helperText: "Selects the codebook used for extraction.",
      },
      {
        key: "disease",
        label: "Disease / condition",
        type: "text",
        placeholder: "covid19",
        defaultValue: "covid19",
        helperText: "Routes to dataset/codebook directories.",
      },
      {
        key: "stage",
        label: "Pipeline stage",
        type: "select",
        options: [
          { value: "fetch", label: "Fetch — download PDFs only" },
          { value: "index", label: "Index — parse fetched PDFs" },
          { value: "extract", label: "Extract — LLM coding (runs fetch+index)" },
          { value: "both", label: "Both — index + extract" },
        ],
        defaultValue: "extract",
        helperText: "How far to run the coding pipeline.",
      },
      {
        key: "fetch_strategy",
        label: "Full-text source",
        type: "select",
        options: [
          { value: "pmc_only", label: "PMC only (open access)" },
          { value: "pmc_scihub_manual", label: "PMC + Sci-Hub + manual fallback" },
        ],
        defaultValue: "pmc_only",
        helperText: "Where to source full-text PDFs.",
      },
      {
        key: "profile",
        label: "Profile / topic",
        type: "text",
        placeholder: "dataset profile id",
        helperText: "Coding project profile (dataset subfolder). Required by the dataset layout.",
        advanced: true,
      },
      {
        key: "codebook_path",
        label: "Codebook path (override)",
        type: "text",
        placeholder: "configs/<disease>/codebooks/<parameter>.yaml",
        helperText: "Defaults to the disease + parameter codebook.",
        advanced: true,
      },
    ],
  },
  5: {
    stepNumber: 5,
    blurb:
      "Pool the coded estimates into a meta-analytic summary. Pick the effect model and effect measure; toggle transforms for skewed parameters.",
    fields: [
      {
        key: "method",
        label: "Effect model",
        type: "select",
        options: [
          { value: "random", label: "Random effects" },
          { value: "fixed", label: "Fixed effect" },
        ],
        defaultValue: "random",
        helperText: "Random effects allows between-study heterogeneity (usually preferred).",
      },
      {
        key: "estimate_measure",
        label: "Effect measure",
        type: "select",
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
        placeholder: "disease_name",
        helperText: "Optional column to produce subgroup estimates. Blank = pool all.",
      },
      {
        key: "log_transform",
        label: "Log-transform before pooling",
        type: "switch",
        helperText: "Pool log(estimate) then back-transform. Use for skewed/positive parameters.",
        advanced: true,
      },
      {
        key: "include_median",
        label: "Include median rows",
        type: "switch",
        helperText: "Treat median rows as means (mean measure only).",
        advanced: true,
      },
      {
        key: "impute_missing_se",
        label: "Impute missing SE",
        type: "switch",
        defaultValue: "true",
        helperText: "Use a conservative SE for rows lacking CI/SD/SE (on by default).",
        advanced: true,
      },
      {
        key: "parameter_type",
        label: "Parameter type filter",
        type: "text",
        placeholder: "serial_interval",
        helperText: "Filter coded rows by parameter_type. Inherited from Step 1 if blank.",
        advanced: true,
      },
    ],
  },
}

export function getStepConfig(stepNumber: number): StepConfig | undefined {
  return STEP_CONFIGS[stepNumber]
}
