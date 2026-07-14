import { getApiBaseUrl } from "@/lib/config"

export type RunEvent = {
  id: number
  run_id: string
  step_no: number | null
  level: string
  message: string
  ts: string
}

export type SubscribeToRunEventsOptions = {
  onEvent: (event: RunEvent) => void
  onError?: (event: Event) => void
  signal?: AbortSignal
}

export type GetRunEventsOptions = {
  limit?: number
  signal?: AbortSignal
}

export async function getRunEvents(
  runId: string,
  { limit = 500, signal }: GetRunEventsOptions = {},
): Promise<RunEvent[]> {
  const base = getApiBaseUrl().replace(/\/$/, "")
  const params = new URLSearchParams({ limit: String(limit) })
  const response = await fetch(
    `${base}/runs/${encodeURIComponent(runId)}/events/history?${params}`,
    { signal },
  )

  if (!response.ok) {
    throw new Error(`Events request failed (${response.status})`)
  }

  return (await response.json()) as RunEvent[]
}

export function subscribeToRunEvents(
  runId: string,
  { onEvent, onError, signal }: SubscribeToRunEventsOptions,
): () => void {
  const source = new EventSource(
    `${getApiBaseUrl()}/runs/${encodeURIComponent(runId)}/events`,
  )

  const close = () => {
    source.close()
  }

  if (signal?.aborted) {
    close()
    return close
  }

  const handleEvent = (event: MessageEvent<string>) => {
    onEvent(JSON.parse(event.data) as RunEvent)
  }

  source.addEventListener("run_event", handleEvent)
  source.onerror = (event) => {
    onError?.(event)
  }
  signal?.addEventListener("abort", close, { once: true })

  return close
}
