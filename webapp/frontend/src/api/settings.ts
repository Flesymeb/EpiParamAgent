import { getApiBaseUrl } from "@/lib/config"

export type LLMModuleId = "screening" | "coding"
export type VerifySslValue = "default" | "true" | "false"

export type LLMProfileRead = {
  provider: string
  model: string
  api_base: string
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

export type LLMSettingsRead = {
  profiles: Record<LLMModuleId, LLMProfileRead>
}

export type LLMProfileUpdate = {
  provider?: string
  model?: string
  api_base?: string
  api_key?: string
  clear_api_key?: boolean
  temperature?: string
  max_tokens?: string
  timeout_s?: string
  verify_ssl?: VerifySslValue
}

export type LLMSettingsUpdate = {
  profiles: Partial<Record<LLMModuleId, LLMProfileUpdate>>
}

export async function getLLMSettings(
  signal?: AbortSignal
): Promise<LLMSettingsRead> {
  const response = await fetch(`${apiBase()}/settings/llm`, { signal })
  if (!response.ok) {
    throw new Error(await responseError(response, "Failed to load LLM settings"))
  }
  return (await response.json()) as LLMSettingsRead
}

export async function updateLLMSettings(
  body: LLMSettingsUpdate
): Promise<LLMSettingsRead> {
  const response = await fetch(`${apiBase()}/settings/llm`, {
    body: JSON.stringify(body),
    headers: {
      "Content-Type": "application/json",
    },
    method: "PUT",
  })
  if (!response.ok) {
    throw new Error(await responseError(response, "Failed to save LLM settings"))
  }
  return (await response.json()) as LLMSettingsRead
}

function apiBase() {
  return getApiBaseUrl().replace(/\/$/, "")
}

async function responseError(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    if (typeof payload.detail === "string" && payload.detail) {
      return payload.detail
    }
  } catch {
    // Use the fallback below when the response body is not JSON.
  }
  return `${fallback} (${response.status})`
}
