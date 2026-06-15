import { getApiBaseUrl } from "@/lib/config"

export type StagePrompt = {
  stage: string
  has_prompt: boolean
  source: string | null
  system: string | null
  user: string | null
  output: string | null
}

export type StagePromptQuery = {
  disease?: string
  parameter?: string
  strategy?: string
}

/** Read-only prompt template a stage uses (for display + supplementation). */
export async function getStagePrompt(
  stage: string,
  query: StagePromptQuery = {},
  signal?: AbortSignal
): Promise<StagePrompt> {
  const base = getApiBaseUrl().replace(/\/$/, "")
  const params = new URLSearchParams()
  if (query.disease) params.set("disease", query.disease)
  if (query.parameter) params.set("parameter", query.parameter)
  if (query.strategy) params.set("strategy", query.strategy)
  const qs = params.toString()
  const response = await fetch(
    `${base}/prompts/${encodeURIComponent(stage)}${qs ? `?${qs}` : ""}`,
    { signal }
  )
  if (!response.ok) {
    throw new Error(`Prompt request failed (${response.status})`)
  }
  return (await response.json()) as StagePrompt
}
