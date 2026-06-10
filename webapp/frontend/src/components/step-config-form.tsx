import { useEffect, useMemo, useState } from "react"
import { ChevronsUpDownIcon } from "lucide-react"

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

export function StepConfigForm({
  stepNumber,
  initialValues,
  onChange,
  disabled = false,
}: StepConfigFormProps) {
  const config = getStepConfig(stepNumber)
  const fields = useMemo(() => config?.fields ?? [], [config])
  const initial = useMemo(
    () => seedValues(fields, initialValues),
    [fields, initialValues]
  )

  const [values, setValues] = useState<Record<string, FieldValue>>(initial)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  // Seed parent state on mount (the form is keyed by step, so it remounts and
  // re-seeds whenever the active step changes).
  useEffect(() => {
    onChange(toParams(fields, initial))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!config) {
    return null
  }

  function update(key: string, value: FieldValue) {
    setValues((prev) => {
      const next = { ...prev, [key]: value }
      onChange(toParams(fields, next))
      return next
    })
  }

  const basicFields = fields.filter((field) => !field.advanced)
  const advancedFields = fields.filter((field) => field.advanced)

  return (
    <div className="space-y-4 rounded-lg border bg-muted/15 p-4">
      <p className="text-sm text-muted-foreground">{config.blurb}</p>

      <div className="grid gap-4 sm:grid-cols-2">
        {basicFields.map((field) => (
          <Field
            disabled={disabled}
            field={field}
            key={field.key}
            onChange={update}
            value={values[field.key]}
          />
        ))}
      </div>

      {advancedFields.length > 0 ? (
        <Collapsible onOpenChange={setAdvancedOpen} open={advancedOpen}>
          <CollapsibleTrigger
            className="flex w-full items-center justify-between rounded-md border border-dashed px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/40"
            disabled={disabled}
          >
            Advanced settings
            <ChevronsUpDownIcon className="size-4" />
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-4">
            <div className="grid gap-4 sm:grid-cols-2">
              {advancedFields.map((field) => (
                <Field
                  disabled={disabled}
                  field={field}
                  key={field.key}
                  onChange={update}
                  value={values[field.key]}
                />
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      ) : null}
    </div>
  )
}

function Field({
  field,
  value,
  onChange,
  disabled,
}: {
  field: StepField
  value: FieldValue
  onChange: (key: string, value: FieldValue) => void
  disabled: boolean
}) {
  const fieldId = `step-field-${field.key}`

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
        "space-y-1.5",
        (field.type === "textarea") && "sm:col-span-2"
      )}
    >
      <label className="text-xs font-medium" htmlFor={fieldId}>
        {field.label}
      </label>

      {field.type === "select" ? (
        <Select
          disabled={disabled}
          onValueChange={(next) => onChange(field.key, next)}
          value={typeof value === "string" ? value : ""}
        >
          <SelectTrigger className="w-full" id={fieldId}>
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
          disabled={disabled}
          id={fieldId}
          onChange={(event) => onChange(field.key, event.target.value)}
          placeholder={field.placeholder}
          rows={3}
          value={typeof value === "string" ? value : ""}
        />
      ) : (
        <Input
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

      {field.helperText ? (
        <p className="text-xs text-muted-foreground">{field.helperText}</p>
      ) : null}
    </div>
  )
}
