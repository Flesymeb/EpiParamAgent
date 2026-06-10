import { API_BASE_URL } from "@/lib/config"

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

export function subscribeToRunEvents(
  runId: string,
  { onEvent, onError, signal }: SubscribeToRunEventsOptions,
): () => void {
  const source = new EventSource(
    `${API_BASE_URL}/runs/${encodeURIComponent(runId)}/events`,
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
