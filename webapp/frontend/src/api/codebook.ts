import { getApiBaseUrl } from "@/lib/config"

export type CodebookField = {
  name: string | null
  label: string | null
  type: string | null
  required: boolean
  prompt: string | null
}

export type Codebook = {
  disease: string
  parameter: string
  name: string | null
  description: string | null
  effect_type: string | null
  notes: string | null
  fields: CodebookField[]
}

/** Fetch the read-only codebook schema for a disease + parameter. */
export async function getCodebook(
  disease: string,
  parameter: string,
  signal?: AbortSignal
): Promise<Codebook> {
  const base = getApiBaseUrl().replace(/\/$/, "")
  const response = await fetch(
    `${base}/codebooks/${encodeURIComponent(disease)}/${encodeURIComponent(parameter)}`,
    { signal }
  )
  if (!response.ok) {
    throw new Error(`Codebook request failed (${response.status})`)
  }
  return (await response.json()) as Codebook
}
