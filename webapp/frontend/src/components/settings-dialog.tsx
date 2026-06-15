import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import {
  BrainCircuitIcon,
  PaletteIcon,
  PlugIcon,
  SlidersHorizontalIcon,
  WrenchIcon,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { useTheme } from "next-themes"
import { toast } from "sonner"

import {
  getLLMSettings,
  updateLLMSettings,
} from "@/api/settings"
import type {
  LLMModuleId,
  LLMProfileRead,
  VerifySslValue,
} from "@/api/settings"
import { HintTooltip } from "@/components/hint-tooltip"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import { getErrorMessage } from "@/lib/errors"
import { useSettings } from "@/lib/settings"
import { cn } from "@/lib/utils"

type SettingsDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
}

const themeOptions = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
] as const

const diseaseOptions = ["mpox", "covid19"] as const
const parameterOptions = [
  "serial_interval",
  "reproduction_number",
  "fatality",
] as const

type LLMProfileForm = {
  provider: string
  model: string
  api_base: string
  api_key: string
  clear_api_key: boolean
  temperature: string
  max_tokens: string
  timeout_s: string
  verify_ssl: VerifySslValue
  has_api_key: boolean
  has_module_api_key: boolean
  api_key_hint: string
  resolved_provider: string
  resolved_model: string
  resolved_api_base: string
}

const llmModules: Array<{
  id: LLMModuleId
  label: string
  description: string
  envPrefix: string
}> = [
  {
    id: "screening",
    label: "Screening",
    description: "Used by query generation and title/abstract screening.",
    envPrefix: "SCREENING_LLM_*",
  },
  {
    id: "coding",
    label: "Coding",
    description: "Used by full-text coding and extraction.",
    envPrefix: "CODING_LLM_*",
  },
]

const settingsCategories = [
  {
    value: "appearance",
    label: "Appearance",
    description: "Theme",
    icon: PaletteIcon,
  },
  {
    value: "connection",
    label: "Connection",
    description: "Backend URL",
    icon: PlugIcon,
  },
  {
    value: "llm",
    label: "LLM",
    description: "Provider, model",
    icon: BrainCircuitIcon,
  },
  {
    value: "run-defaults",
    label: "Run defaults",
    description: "Disease, parameter",
    icon: SlidersHorizontalIcon,
  },
  {
    value: "advanced",
    label: "Advanced",
    description: "Local options",
    icon: WrenchIcon,
  },
] as const

export function SettingsDialog({
  open,
  onOpenChange,
}: SettingsDialogProps) {
  const { settings, update, reset } = useSettings()
  const { theme, setTheme } = useTheme()
  const activeTheme = theme ?? "system"
  const [llmProfiles, setLlmProfiles] = useState(() => createEmptyProfiles())
  const [llmLoadError, setLlmLoadError] = useState<string | null>(null)
  const [isLoadingLLM, setIsLoadingLLM] = useState(false)
  const [isSavingLLM, setIsSavingLLM] = useState(false)

  useEffect(() => {
    if (!open) {
      return
    }

    const controller = new AbortController()

    Promise.resolve()
      .then(() => {
        if (controller.signal.aborted) {
          return null
        }
        setIsLoadingLLM(true)
        setLlmLoadError(null)
        return getLLMSettings(controller.signal)
      })
      .then((payload) => {
        if (!payload) {
          return
        }
        setLlmProfiles(profilesFromRead(payload.profiles))
      })
      .catch((error) => {
        if (controller.signal.aborted) {
          return
        }
        setLlmLoadError(getErrorMessage(error))
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsLoadingLLM(false)
        }
      })

    return () => controller.abort()
  }, [open])

  function updateLlmProfile(
    moduleId: LLMModuleId,
    patch: Partial<LLMProfileForm>
  ) {
    setLlmProfiles((current) => ({
      ...current,
      [moduleId]: {
        ...current[moduleId],
        ...patch,
      },
    }))
  }

  async function handleSaveLLMSettings() {
    setIsSavingLLM(true)
    setLlmLoadError(null)
    try {
      const payload = await updateLLMSettings({
        profiles: Object.fromEntries(
          llmModules.map((module) => [
            module.id,
            profileToUpdate(llmProfiles[module.id]),
          ])
        ),
      })
      setLlmProfiles(profilesFromRead(payload.profiles))
      toast.success("LLM settings saved")
    } catch (error) {
      const message = getErrorMessage(error)
      setLlmLoadError(message)
      toast.error(message)
    } finally {
      setIsSavingLLM(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="h-[min(88vh,560px)] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0 sm:max-w-[920px]">
        <DialogHeader className="px-5 pt-5 pr-12 pb-4">
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>
            Configure local UI preferences, backend connection, and run
            defaults.
          </DialogDescription>
        </DialogHeader>

        <Tabs
          className="min-h-0 flex-col gap-0 overflow-hidden border-t sm:grid sm:grid-cols-[13.5rem_minmax(0,1fr)]"
          defaultValue={settingsCategories[0].value}
          orientation="vertical"
        >
          <TabsList
            className="max-h-40 w-full items-stretch justify-start gap-1 overflow-y-auto rounded-none border-b bg-muted/25 p-2 sm:max-h-none sm:border-r sm:border-b-0 sm:bg-muted/20"
            variant="line"
          >
            {settingsCategories.map((item) => {
              const Icon = item.icon

              return (
                <TabsTrigger
                  className="h-auto w-full justify-start gap-2 px-2.5 py-2 text-left"
                  key={item.value}
                  value={item.value}
                >
                  <Icon className="size-4 text-muted-foreground" />
                  <span className="grid min-w-0 flex-1 gap-0.5">
                    <span className="truncate text-sm font-medium">
                      {item.label}
                    </span>
                    <span className="truncate text-xs font-normal text-muted-foreground">
                      {item.description}
                    </span>
                  </span>
                </TabsTrigger>
              )
            })}
          </TabsList>

          <div className="min-h-0 overflow-y-auto p-4 sm:p-5">
            <TabsContent value="appearance" className="mt-0 space-y-4">
              <section className="space-y-3">
                <SectionHeading icon={PaletteIcon} title="Appearance" />
                <div className="grid grid-cols-3 gap-2">
                  {themeOptions.map((option) => (
                    <Button
                      className={cn(
                        activeTheme === option.value &&
                          "border-primary/35 bg-primary/10 text-primary hover:bg-primary/15"
                      )}
                      key={option.value}
                      onClick={() => setTheme(option.value)}
                      type="button"
                      variant="outline"
                    >
                      {option.label}
                    </Button>
                  ))}
                </div>
              </section>
            </TabsContent>

            <TabsContent value="connection" className="mt-0 space-y-4">
              <section className="space-y-3">
                <SectionHeading icon={PlugIcon} title="Connection" />
                <div className="space-y-1.5">
                  <FieldLabel
                    hint="Overrides the API base URL used by the frontend. Reload after changing it so all API clients use the new value."
                    htmlFor="settings-backend-url"
                    label="About backend URL"
                  >
                    Backend URL
                  </FieldLabel>
                  <Input
                    id="settings-backend-url"
                    onChange={(event) =>
                      update({ backendUrl: event.target.value })
                    }
                    placeholder="/api"
                    value={settings.backendUrl}
                  />
                </div>
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-xs text-muted-foreground">
                    Changes apply after reload.
                  </p>
                  <Button
                    onClick={() => window.location.reload()}
                    type="button"
                    variant="outline"
                  >
                    Apply & reload
                  </Button>
                </div>
              </section>
            </TabsContent>

            <TabsContent value="llm" className="mt-0 space-y-4">
              <section className="space-y-3">
                <SectionHeading icon={BrainCircuitIcon} title="LLM" />
                <div className="flex flex-col gap-2 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
                  <p>
                    Saved to backend .env.local. Full API keys are never
                    returned to the browser after saving.
                  </p>
                  {llmLoadError ? (
                    <span className="text-destructive">{llmLoadError}</span>
                  ) : isLoadingLLM ? (
                    <span>Loading LLM settings…</span>
                  ) : null}
                </div>
                <div className="grid gap-3 lg:grid-cols-2">
                  {llmModules.map((module) => (
                    <LLMProfilePanel
                      disabled={isLoadingLLM || isSavingLLM}
                      key={module.id}
                      module={module}
                      onChange={(patch) => updateLlmProfile(module.id, patch)}
                      profile={llmProfiles[module.id]}
                    />
                  ))}
                </div>
                <div className="flex justify-end">
                  <Button
                    disabled={isLoadingLLM || isSavingLLM}
                    onClick={() => {
                      void handleSaveLLMSettings()
                    }}
                    type="button"
                  >
                    {isSavingLLM ? "Saving…" : "Save LLM settings"}
                  </Button>
                </div>
              </section>
            </TabsContent>

            <TabsContent value="run-defaults" className="mt-0 space-y-4">
              <section className="space-y-3">
                <SectionHeading
                  icon={SlidersHorizontalIcon}
                  title="Run defaults"
                />
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <FieldLabel htmlFor="settings-default-disease">
                      Default disease
                    </FieldLabel>
                    <Select
                      onValueChange={(defaultDisease) =>
                        update({ defaultDisease })
                      }
                      value={settings.defaultDisease}
                    >
                      <SelectTrigger
                        id="settings-default-disease"
                        className="w-full"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {diseaseOptions.map((option) => (
                            <SelectItem key={option} value={option}>
                              {option}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <FieldLabel htmlFor="settings-default-parameter">
                      Default parameter
                    </FieldLabel>
                    <Select
                      onValueChange={(defaultParameter) =>
                        update({ defaultParameter })
                      }
                      value={settings.defaultParameter}
                    >
                      <SelectTrigger
                        id="settings-default-parameter"
                        className="w-full"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {parameterOptions.map((option) => (
                            <SelectItem key={option} value={option}>
                              {option}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </section>
            </TabsContent>

            <TabsContent value="advanced" className="mt-0 space-y-4">
              <section className="space-y-3">
                <SectionHeading icon={WrenchIcon} title="Advanced" />
                <p className="text-xs text-muted-foreground">
                  Stored locally; backend wiring pending.
                </p>
                <div className="grid gap-3">
                  <div className="space-y-1.5">
                    <FieldLabel
                      hint="Reserved proxy setting for future backend routing."
                      htmlFor="settings-proxy"
                      label="About proxy"
                    >
                      Proxy
                    </FieldLabel>
                    <Input
                      id="settings-proxy"
                      onChange={(event) =>
                        update({ proxy: event.target.value })
                      }
                      value={settings.proxy}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <FieldLabel
                      hint="Reserved local skills path for future agent integration."
                      htmlFor="settings-skills-path"
                      label="About skills path"
                    >
                      Skills path
                    </FieldLabel>
                    <Input
                      id="settings-skills-path"
                      onChange={(event) =>
                        update({ skillsPath: event.target.value })
                      }
                      value={settings.skillsPath}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <FieldLabel
                      hint="Reserved tool allowlist or configuration placeholder."
                      htmlFor="settings-tools"
                      label="About tools"
                    >
                      Tools
                    </FieldLabel>
                    <Input
                      id="settings-tools"
                      onChange={(event) =>
                        update({ tools: event.target.value })
                      }
                      value={settings.tools}
                    />
                  </div>
                </div>
              </section>
            </TabsContent>
          </div>
        </Tabs>

        <DialogFooter className="mx-0 mb-0 px-5">
          <Button onClick={reset} type="button" variant="outline">
            Reset to defaults
          </Button>
          <Button onClick={() => onOpenChange(false)} type="button">
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function LLMProfilePanel({
  disabled,
  module,
  onChange,
  profile,
}: {
  disabled: boolean
  module: (typeof llmModules)[number]
  onChange: (patch: Partial<LLMProfileForm>) => void
  profile: LLMProfileForm
}) {
  const fieldPrefix = `settings-llm-${module.id}`

  return (
    <div className="space-y-3 rounded-lg border bg-muted/15 p-3">
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-sm font-medium">{module.label}</h4>
          <span className="rounded-full border bg-background px-2 py-0.5 text-[0.7rem] text-muted-foreground">
            {module.envPrefix}
          </span>
        </div>
        <p className="text-xs text-muted-foreground">{module.description}</p>
        <p className="truncate text-xs text-muted-foreground">
          Effective: {profile.resolved_provider || "default"} /{" "}
          {profile.resolved_model || "default"}
        </p>
      </div>

      <div className="grid gap-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
          <div className="space-y-1.5">
            <FieldLabel htmlFor={`${fieldPrefix}-provider`}>
              Provider
            </FieldLabel>
            <Input
              disabled={disabled}
              id={`${fieldPrefix}-provider`}
              onChange={(event) => onChange({ provider: event.target.value })}
              placeholder="openrouter, openai, lab, lab2"
              value={profile.provider}
            />
          </div>
          <div className="space-y-1.5">
            <FieldLabel htmlFor={`${fieldPrefix}-model`}>Model</FieldLabel>
            <Input
              disabled={disabled}
              id={`${fieldPrefix}-model`}
              onChange={(event) => onChange({ model: event.target.value })}
              placeholder="empty = backend fallback"
              value={profile.model}
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <FieldLabel
            hint="OpenAI-compatible base URL for this module. Stored as *_LLM_API_BASE in .env.local."
            htmlFor={`${fieldPrefix}-api-base`}
            label={`About ${module.label} API base`}
          >
            API Base URL
          </FieldLabel>
          <Input
            disabled={disabled}
            id={`${fieldPrefix}-api-base`}
            onChange={(event) => onChange({ api_base: event.target.value })}
            placeholder="https://.../v1"
            value={profile.api_base}
          />
          {profile.resolved_api_base ? (
            <p
              className="truncate text-xs text-muted-foreground"
              title={profile.resolved_api_base}
            >
              Effective base: {profile.resolved_api_base}
            </p>
          ) : null}
        </div>

        <div className="space-y-1.5">
          <FieldLabel
            hint="Saved to backend .env.local. The current key is never sent back to the browser."
            htmlFor={`${fieldPrefix}-api-key`}
            label={`About ${module.label} API key`}
          >
            API Key
          </FieldLabel>
          <Input
            autoComplete="off"
            disabled={disabled || profile.clear_api_key}
            id={`${fieldPrefix}-api-key`}
            onChange={(event) => onChange({ api_key: event.target.value })}
            placeholder={
              profile.has_api_key
                ? `configured ${profile.api_key_hint}`
                : "not configured"
            }
            type="password"
            value={profile.api_key}
          />
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">
              {formatApiKeyStatus(profile)}
            </span>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <Switch
                checked={profile.clear_api_key}
                disabled={disabled || !profile.has_module_api_key}
                onCheckedChange={(checked) =>
                  onChange({
                    api_key: checked ? "" : profile.api_key,
                    clear_api_key: checked,
                  })
                }
                size="sm"
              />
              Clear module key
            </label>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
          <div className="space-y-1.5">
            <FieldLabel htmlFor={`${fieldPrefix}-temperature`}>
              Temperature
            </FieldLabel>
            <Input
              disabled={disabled}
              id={`${fieldPrefix}-temperature`}
              max={2}
              min={0}
              onChange={(event) =>
                onChange({ temperature: event.target.value })
              }
              placeholder="empty = default"
              step={0.1}
              type="number"
              value={profile.temperature}
            />
          </div>
          <div className="space-y-1.5">
            <FieldLabel htmlFor={`${fieldPrefix}-max-tokens`}>
              Max tokens
            </FieldLabel>
            <Input
              disabled={disabled}
              id={`${fieldPrefix}-max-tokens`}
              min={1}
              onChange={(event) =>
                onChange({ max_tokens: event.target.value })
              }
              placeholder="empty = default"
              step={1}
              type="number"
              value={profile.max_tokens}
            />
          </div>
          <div className="space-y-1.5">
            <FieldLabel htmlFor={`${fieldPrefix}-timeout`}>
              Timeout seconds
            </FieldLabel>
            <Input
              disabled={disabled}
              id={`${fieldPrefix}-timeout`}
              min={1}
              onChange={(event) => onChange({ timeout_s: event.target.value })}
              placeholder="empty = default"
              step={1}
              type="number"
              value={profile.timeout_s}
            />
          </div>
          <div className="space-y-1.5">
            <FieldLabel htmlFor={`${fieldPrefix}-verify-ssl`}>
              Verify SSL
            </FieldLabel>
            <Select
              disabled={disabled}
              onValueChange={(verify_ssl) =>
                onChange({ verify_ssl: verify_ssl as VerifySslValue })
              }
              value={profile.verify_ssl}
            >
              <SelectTrigger
                id={`${fieldPrefix}-verify-ssl`}
                className="w-full"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="default">Server default</SelectItem>
                  <SelectItem value="true">Enabled</SelectItem>
                  <SelectItem value="false">Disabled</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
    </div>
  )
}

function SectionHeading({
  icon: Icon,
  title,
}: {
  icon: LucideIcon
  title: string
}) {
  return (
    <h3 className="flex items-center gap-2 text-sm font-medium">
      <Icon className="size-4 text-muted-foreground" />
      {title}
    </h3>
  )
}

function createEmptyProfile(): LLMProfileForm {
  return {
    provider: "",
    model: "",
    api_base: "",
    api_key: "",
    clear_api_key: false,
    temperature: "",
    max_tokens: "",
    timeout_s: "",
    verify_ssl: "default",
    has_api_key: false,
    has_module_api_key: false,
    api_key_hint: "",
    resolved_provider: "",
    resolved_model: "",
    resolved_api_base: "",
  }
}

function createEmptyProfiles(): Record<LLMModuleId, LLMProfileForm> {
  return {
    screening: createEmptyProfile(),
    coding: createEmptyProfile(),
  }
}

function profilesFromRead(
  profiles: Record<LLMModuleId, LLMProfileRead>
): Record<LLMModuleId, LLMProfileForm> {
  return {
    screening: profileFromRead(profiles.screening),
    coding: profileFromRead(profiles.coding),
  }
}

function profileFromRead(profile: LLMProfileRead): LLMProfileForm {
  return {
    provider: profile.provider,
    model: profile.model,
    api_base: profile.api_base,
    api_key: "",
    clear_api_key: false,
    temperature: profile.temperature,
    max_tokens: profile.max_tokens,
    timeout_s: profile.timeout_s,
    verify_ssl: profile.verify_ssl,
    has_api_key: profile.has_api_key,
    has_module_api_key: profile.has_module_api_key,
    api_key_hint: profile.api_key_hint,
    resolved_provider: profile.resolved_provider,
    resolved_model: profile.resolved_model,
    resolved_api_base: profile.resolved_api_base,
  }
}

function profileToUpdate(profile: LLMProfileForm) {
  const apiKey = profile.api_key.trim()
  return {
    provider: profile.provider,
    model: profile.model,
    api_base: profile.api_base,
    ...(apiKey ? { api_key: apiKey } : {}),
    clear_api_key: profile.clear_api_key,
    temperature: profile.temperature,
    max_tokens: profile.max_tokens,
    timeout_s: profile.timeout_s,
    verify_ssl: profile.verify_ssl,
  }
}

function formatApiKeyStatus(profile: LLMProfileForm) {
  if (profile.has_module_api_key) {
    return `Module key: ${profile.api_key_hint}`
  }
  if (profile.has_api_key) {
    return `Provider/default key: ${profile.api_key_hint}`
  }
  return "No effective key"
}

function FieldLabel({
  children,
  hint,
  htmlFor,
  label,
}: {
  children: ReactNode
  hint?: ReactNode
  htmlFor: string
  label?: string
}) {
  return (
    <label
      className="flex items-center gap-1.5 text-xs font-medium"
      htmlFor={htmlFor}
    >
      {children}
      {hint ? (
        <HintTooltip content={hint} label={label ?? "More info"} />
      ) : null}
    </label>
  )
}
