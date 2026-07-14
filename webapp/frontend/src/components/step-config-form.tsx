import { useCallback, useEffect, useMemo, useState } from "react"
import {
  BookOpenIcon,
  CalendarRangeIcon,
  ChevronsUpDownIcon,
  CpuIcon,
  DatabaseIcon,
  DownloadIcon,
  FilterIcon,
  LayersIcon,
  ListChecksIcon,
  PlusIcon,
  SearchIcon,
  SigmaIcon,
  SlidersHorizontalIcon,
  TableIcon,
  TargetIcon,
  XIcon,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { CodebookPanel } from "@/components/codebook-panel"
import { PromptPanel } from "@/components/prompt-panel"
import { SectionCard } from "@/components/section-card"
import { HintTooltip } from "@/components/hint-tooltip"
import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { getStepConfig } from "@/lib/step-config"
import type { StepField } from "@/lib/step-config"
import { cn } from "@/lib/utils"

type FieldValue = string | boolean

type StepConfigFormProps = {
  stepNumber: number
  initialValues: Record<string, unknown>
  onChange: (params: Record<string, unknown>) => void
  disabled?: boolean
}

function toBool(value: unknown): boolean {
  if (typeof value === "boolean") return value
  if (typeof value === "number") return value !== 0
  if (typeof value === "string") return ["true", "1", "yes", "on"].includes(value.toLowerCase())
  return false
}

function seedValues(
  fields: StepField[],
  initialValues: Record<string, unknown>
): Record<string, FieldValue> {
  const out: Record<string, FieldValue> = {}
  for (const field of fields) {
    const inherited = initialValues[field.key]
    const hasInherited = inherited !== undefined && inherited !== null
    if (field.type === "switch") {
      out[field.key] = hasInherited ? toBool(inherited) : toBool(field.defaultValue)
    } else {
      // Inherited run params win over schema defaults so a step form never
      // clobbers run-level values (e.g. disease set at run creation).
      out[field.key] = hasInherited ? String(inherited) : field.defaultValue ?? ""
    }
  }
  return out
}

function toParams(
  fields: StepField[],
  values: Record<string, FieldValue>
): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  for (const field of fields) {
    const value = values[field.key]
    if (field.type === "switch") {
      params[field.key] = Boolean(value)
    } else if (typeof value === "string") {
      params[field.key] = value.trim()
    }
  }
  return params
}

// Per-group icons for the configuration board panels.
const GROUP_ICONS: Record<string, LucideIcon> = {
  "Research question": TargetIcon,
  "Search scope": CalendarRangeIcon,
  Search: SearchIcon,
  Filters: FilterIcon,
  Eligibility: ListChecksIcon,
  "Batch & strategy": LayersIcon,
  Source: DatabaseIcon,
  "Indexing & fetch": DownloadIcon,
  Codebook: BookOpenIcon,
  "Effect model": SigmaIcon,
  "Subgroups & filters": FilterIcon,
  Transforms: SlidersHorizontalIcon,
  Model: CpuIcon,
}

// LLM stages that expose a prompt template + per-stage reviewer supplement.
// (UI step numbers; Code=4 & Extraction=5 both feed the coding step.)
const PROMPT_STAGES: Record<number, { stage: string; key: string }> = {
  1: { stage: "query", key: "query_prompt_supplement" },
  3: { stage: "screen", key: "screen_prompt_supplement" },
  4: { stage: "code", key: "code_prompt_supplement" },
  5: { stage: "extract", key: "code_prompt_supplement" },
}

const fieldControlClass =
  "h-8 rounded-lg bg-background px-2.5 text-sm shadow-xs dark:bg-input/30"

export function StepConfigForm({
  stepNumber,
  initialValues,
  onChange,
  disabled = false,
}: StepConfigFormProps) {
  const config = getStepConfig(stepNumber)
  const fields = useMemo(() => config?.fields ?? [], [config])
  const promptMeta = config ? PROMPT_STAGES[config.stepNumber] : undefined
  const supplementKey = promptMeta?.key
  const initial = useMemo(() => {
    const seeded = seedValues(fields, initialValues)
    if (supplementKey) {
      seeded[supplementKey] = String(initialValues[supplementKey] ?? "")
    }
    return seeded
  }, [fields, initialValues, supplementKey])

  const [values, setValues] = useState<Record<string, FieldValue>>(initial)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const buildParams = useCallback(
    (next: Record<string, FieldValue>) => {
      const params = toParams(fields, next)
      if (supplementKey) {
        params[supplementKey] = String(next[supplementKey] ?? "").trim()
      }
      return params
    },
    [fields, supplementKey]
  )

  // Seed parent state on mount (the form is keyed by step, so it remounts and
  // re-seeds whenever the active step changes).
  useEffect(() => {
    onChange(buildParams(initial))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!config) {
    return null
  }

  function update(key: string, value: FieldValue) {
    setValues((prev) => {
      const next = { ...prev, [key]: value }
      onChange(buildParams(next))
      return next
    })
  }

  const basicFields = fields.filter((field) => !field.advanced)
  const advancedFields = fields.filter((field) => field.advanced)
  const basicGroups = groupFields(basicFields)
  const advancedGroups = groupFields(advancedFields)
  const hasSupplementaryPanels =
    advancedFields.length > 0 ||
    config.stepNumber === 4 ||
    Boolean(promptMeta && supplementKey)

  return (
    <div className="min-w-0 space-y-2.5 sm:space-y-3">
      {basicGroups.length > 0 ? (
        <SectionCard
          icon={GROUP_ICONS[basicGroups[0]?.title ?? ""] ?? SlidersHorizontalIcon}
          title={basicGroups[0]?.title || "Settings"}
        >
          <div className="space-y-3 sm:space-y-4">
            <p className="text-sm leading-5 text-muted-foreground">
              {config.blurb}
            </p>
            {basicGroups.map((group, index) => {
              const GroupIcon = GROUP_ICONS[group.title] ?? SlidersHorizontalIcon

              return (
                <div
                  className={cn(
                    "space-y-2.5",
                    index > 0 && "border-t border-border/70 pt-3 sm:pt-4"
                  )}
                  key={group.title || `group-${index}`}
                >
                  {index > 0 && group.title ? (
                    <div className="flex min-w-0 items-center gap-2 text-xs font-medium text-muted-foreground">
                      <GroupIcon className="size-3.5 shrink-0 text-primary" />
                      <span className="min-w-0 truncate">{group.title}</span>
                    </div>
                  ) : null}
                  <div className="grid gap-3">
                    {group.fields.map((field) => (
                      <Field
                        disabled={disabled}
                        field={field}
                        key={field.key}
                        onChange={update}
                        value={values[field.key]}
                        wide={group.fields.length === 1}
                      />
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </SectionCard>
      ) : null}

      {basicGroups.length === 0 ? (
        <SectionCard
          icon={TableIcon}
          title={config.stepNumber === 5 ? "Extraction" : "Stage"}
        >
          <p className="text-sm text-muted-foreground">{config.blurb}</p>
        </SectionCard>
      ) : null}

      {hasSupplementaryPanels ? (
        <>
          {advancedFields.length > 0 ? (
            <div className="overflow-hidden rounded-lg border border-border/70 bg-card shadow-xs">
              <Collapsible onOpenChange={setAdvancedOpen} open={advancedOpen}>
                <CollapsibleTrigger
                  className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm font-medium transition-colors hover:bg-muted/40"
                  disabled={disabled}
                >
                  <SlidersHorizontalIcon className="size-4 text-primary" />
                  <span className="min-w-0 flex-1">Advanced settings</span>
                  <ChevronsUpDownIcon className="size-4 text-muted-foreground" />
                </CollapsibleTrigger>
                <CollapsibleContent className="max-h-[min(48vh,420px)] space-y-3 overflow-y-auto overscroll-contain border-t p-3 shadow-[inset_0_-18px_18px_-22px_var(--muted-foreground)] sm:space-y-4 sm:p-4">
                  {advancedGroups.map((group, index) => (
                    <div className="space-y-2.5" key={group.title || `adv-${index}`}>
                      {group.title ? (
                        <h4 className="text-xs font-medium text-muted-foreground/70">
                          {group.title}
                        </h4>
                      ) : null}
                      <div className="grid gap-3">
                        {group.fields.map((field) => (
                          <Field
                            disabled={disabled}
                            field={field}
                            key={field.key}
                            onChange={update}
                            value={values[field.key]}
                            wide={group.fields.length === 1}
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                </CollapsibleContent>
              </Collapsible>
            </div>
          ) : null}

          {config.stepNumber === 4 ? (
            <CodebookPanel
              disease={typeof values.disease === "string" ? values.disease : ""}
              overridePath={
                typeof values.codebook_path === "string"
                  ? values.codebook_path
                  : ""
              }
              parameter={
                typeof values.parameter === "string" ? values.parameter : ""
              }
            />
          ) : null}

          {promptMeta && supplementKey ? (
            <PromptPanel
              disabled={disabled}
              disease={resolveContext(values, initialValues, "disease")}
              onSupplementChange={(value) => update(supplementKey, value)}
              parameter={resolveContext(values, initialValues, "parameter")}
              stage={promptMeta.stage}
              strategy={resolveContext(values, initialValues, "strategy")}
              supplement={
                typeof values[supplementKey] === "string"
                  ? (values[supplementKey] as string)
                  : ""
              }
            />
          ) : null}
        </>
      ) : null}
    </div>
  )
}

// Read a context value (disease/parameter/strategy) from the form values,
// falling back to the inherited run params (e.g. Extraction has no own fields).
function resolveContext(
  values: Record<string, FieldValue>,
  initialValues: Record<string, unknown>,
  key: string
): string {
  const local = values[key]
  if (typeof local === "string" && local) {
    return local
  }
  const inherited = initialValues[key]
  return typeof inherited === "string" ? inherited : ""
}

// Cluster fields into ordered titled groups (first-appearance order preserved).
function groupFields(
  fields: StepField[]
): { title: string; fields: StepField[] }[] {
  const groups: { title: string; fields: StepField[] }[] = []
  for (const field of fields) {
    const title = field.group ?? ""
    let group = groups.find((candidate) => candidate.title === title)
    if (!group) {
      group = { title, fields: [] }
      groups.push(group)
    }
    group.fields.push(field)
  }
  return groups
}

function Field({
  field,
  value,
  onChange,
  disabled,
  wide = false,
}: {
  field: StepField
  value: FieldValue
  onChange: (key: string, value: FieldValue) => void
  disabled: boolean
  wide?: boolean
}) {
  const fieldId = `step-field-${field.key}`
  const shouldSpanFull =
    wide ||
    field.type === "tags" ||
    field.type === "textarea" ||
    field.type === "year_range"

  if (field.type === "switch") {
    return (
      <div
        className={cn(
          "flex items-start justify-between gap-3 rounded-md border bg-background px-3 py-2.5 sm:col-span-2"
        )}
      >
        <div className="min-w-0 space-y-0.5">
          <label className="text-sm font-medium" htmlFor={fieldId}>
            {field.label}
          </label>
          {field.helperText ? (
            <p className="text-xs text-muted-foreground">{field.helperText}</p>
          ) : null}
        </div>
        <Switch
          checked={Boolean(value)}
          disabled={disabled}
          id={fieldId}
          onCheckedChange={(checked) => onChange(field.key, checked)}
        />
      </div>
    )
  }

  return (
    <div
      className={cn(
        "min-w-0 space-y-1.5",
        shouldSpanFull && "sm:col-span-2"
      )}
    >
      <label className="flex items-center gap-1 text-xs font-medium" htmlFor={fieldId}>
        {field.label}
        {field.helperText ? (
          <HintTooltip content={field.helperText} label={`About ${field.label}`} />
        ) : null}
      </label>

      {field.type === "tags" ? (
        <TagsField
          disabled={disabled}
          id={fieldId}
          onChange={(next) => onChange(field.key, next)}
          placeholder={field.placeholder}
          suggestions={field.suggestions ?? []}
          value={typeof value === "string" ? value : ""}
        />
      ) : field.type === "year_range" ? (
        <YearRangeField
          disabled={disabled}
          id={fieldId}
          onChange={(next) => onChange(field.key, next)}
          value={typeof value === "string" ? value : ""}
        />
      ) : field.type === "select" ? (
        <Select
          disabled={disabled}
          onValueChange={(next) => onChange(field.key, next)}
          value={typeof value === "string" ? value : ""}
        >
          <SelectTrigger className={cn("w-full", fieldControlClass)} id={fieldId}>
            <SelectValue placeholder={field.placeholder ?? "Select…"} />
          </SelectTrigger>
          <SelectContent>
            {field.options?.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : field.type === "textarea" ? (
        <Textarea
          className="rounded-lg bg-background text-sm shadow-xs dark:bg-input/30"
          disabled={disabled}
          id={fieldId}
          onChange={(event) => onChange(field.key, event.target.value)}
          placeholder={field.placeholder}
          rows={3}
          value={typeof value === "string" ? value : ""}
        />
      ) : (
        <Input
          className={cn(
            fieldControlClass,
            field.type === "number" &&
              "[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          )}
          disabled={disabled}
          id={fieldId}
          max={field.max}
          min={field.min}
          onChange={(event) => onChange(field.key, event.target.value)}
          placeholder={field.placeholder}
          step={field.step}
          type={field.type === "number" ? "number" : "text"}
          value={typeof value === "string" ? value : ""}
        />
      )}
    </div>
  )
}

const ANY = "any"
const CURRENT_YEAR = new Date().getFullYear()
const MIN_YEAR = 1990
// Wide open bounds used only when serializing an "Any" side, so an open lower
// bound really means "all earlier years" rather than silently clamping to the
// dropdown's oldest selectable year.
const OPEN_LOW = "1800"
const YEAR_OPTIONS = Array.from(
  { length: CURRENT_YEAR - MIN_YEAR + 1 },
  (_, index) => CURRENT_YEAR - index
)

function parseYearRange(value: string): { from: string; to: string } {
  if (!value) return { from: "", to: "" }
  const [from, to] = value.split(/[:-]/)
  return { from: (from ?? "").trim(), to: (to ?? "").trim() }
}

// Two year Selects (From / To) that serialize to PubMed's `year=YYYY:YYYY`
// format. Local state holds each bound so an open side isn't forced to a
// concrete year on screen even though the emitted range fills it in.
function parseTags(value: string): string[] {
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean)
}

// Chip/token input: removable tags + free-text entry + clickable suggestions.
// Serialized to a comma-joined string (the backend accepts that for keywords).
function TagsField({
  value,
  onChange,
  disabled,
  id,
  suggestions,
  placeholder,
}: {
  value: string
  onChange: (value: string) => void
  disabled: boolean
  id: string
  suggestions: string[]
  placeholder?: string
}) {
  const [draft, setDraft] = useState("")
  const tags = parseTags(value)

  function commitTags(next: string[]) {
    onChange(next.join(", "))
  }

  function addTag(raw: string) {
    const clean = raw.trim().replace(/,+$/, "").trim()
    if (!clean || tags.includes(clean)) {
      setDraft("")
      return
    }
    commitTags([...tags, clean])
    setDraft("")
  }

  function removeTag(tag: string) {
    commitTags(tags.filter((item) => item !== tag))
  }

  const available = suggestions.filter((item) => !tags.includes(item))

  return (
    <div className="min-w-0 space-y-2">
      <div className="flex min-h-8 flex-wrap items-center gap-1.5 rounded-lg border border-input bg-background px-2 py-0 transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50">
        {tags.map((tag) => (
          <Badge className="gap-1 pr-1" key={tag} variant="secondary">
            {tag}
            <button
              aria-label={`Remove ${tag}`}
              className="rounded-full text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
              disabled={disabled}
              onClick={() => removeTag(tag)}
              type="button"
            >
              <XIcon className="size-3" />
            </button>
          </Badge>
        ))}
        <input
          className="h-8 min-w-24 flex-1 bg-transparent text-sm leading-8 outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
          disabled={disabled}
          id={id}
          onBlur={() => addTag(draft)}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === ",") {
              event.preventDefault()
              addTag(draft)
            } else if (
              event.key === "Backspace" &&
              !draft &&
              tags.length > 0
            ) {
              removeTag(tags[tags.length - 1])
            }
          }}
          placeholder={tags.length === 0 ? placeholder : ""}
          value={draft}
        />
      </div>
      {available.length > 0 ? (
        <div className="flex min-w-0 flex-wrap items-center gap-1.5 pb-0.5">
          <span className="shrink-0 text-xs text-muted-foreground">
            Suggestions
          </span>
          {available.map((suggestion) => (
            <button
              className="inline-flex max-w-full shrink-0 items-center gap-0.5 rounded-full border border-dashed bg-background px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:border-solid hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              disabled={disabled}
              key={suggestion}
              onClick={() => addTag(suggestion)}
              type="button"
            >
              <PlusIcon className="size-3" />
              <span className="min-w-0 truncate">{suggestion}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function YearRangeField({
  value,
  onChange,
  disabled,
  id,
}: {
  value: string
  onChange: (value: string) => void
  disabled: boolean
  id: string
}) {
  const [from, setFrom] = useState(() => parseYearRange(value).from)
  const [to, setTo] = useState(() => parseYearRange(value).to)

  function emit(nextFrom: string, nextTo: string) {
    if (!nextFrom && !nextTo) {
      onChange("")
      return
    }
    const lo = nextFrom || OPEN_LOW
    const hi = nextTo || String(CURRENT_YEAR)
    onChange(`${lo}:${hi}`)
  }

  return (
    <div className="flex items-center gap-2">
      <Select
        disabled={disabled}
        onValueChange={(next) => {
          const resolved = next === ANY ? "" : next
          setFrom(resolved)
          emit(resolved, to)
        }}
        value={from || ANY}
      >
        <SelectTrigger className={cn("w-full", fieldControlClass)} id={id}>
          <SelectValue placeholder="From" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ANY}>Any</SelectItem>
          {YEAR_OPTIONS.map((year) => (
            <SelectItem key={year} value={String(year)}>
              {year}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <span className="shrink-0 text-xs text-muted-foreground">to</span>
      <Select
        disabled={disabled}
        onValueChange={(next) => {
          const resolved = next === ANY ? "" : next
          setTo(resolved)
          emit(from, resolved)
        }}
        value={to || ANY}
      >
        <SelectTrigger className={cn("w-full", fieldControlClass)}>
          <SelectValue placeholder="To" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ANY}>Any</SelectItem>
          {YEAR_OPTIONS.map((year) => (
            <SelectItem key={year} value={String(year)}>
              {year}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
