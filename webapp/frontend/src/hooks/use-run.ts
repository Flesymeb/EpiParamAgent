import { useCallback, useEffect, useMemo, useState } from "react"

import { getRun } from "@/api/pipeline"
import type { RunDetail } from "@/api/pipeline"
import { getErrorMessage } from "@/lib/errors"

type RunLoadState = {
  runId: string
  detail: RunDetail | null
  error: string | null
}

export function useRun(runId: string) {
  const [state, setState] = useState<RunLoadState>({
    runId,
    detail: null,
    error: null,
  })

  const refresh = useCallback(async () => {
    try {
      const detail = await getRun(runId)
      setState({ runId, detail, error: null })
      return detail
    } catch (error) {
      const message = getErrorMessage(error)
      setState({ runId, detail: null, error: message })
      throw new Error(message, { cause: error })
    }
  }, [runId])

  useEffect(() => {
    let active = true

    async function loadRun() {
      try {
        const detail = await getRun(runId)
        if (active) {
          setState({ runId, detail, error: null })
        }
      } catch (error) {
        if (active) {
          setState({
            runId,
            detail: null,
            error: getErrorMessage(error),
          })
        }
      }
    }

    void loadRun()

    return () => {
      active = false
    }
  }, [runId])

  return useMemo(() => {
    const isCurrentRun = state.runId === runId
    const detail = isCurrentRun ? state.detail : null
    const error = isCurrentRun ? state.error : null

    return {
      detail,
      error,
      isLoading: detail === null && error === null,
      refresh,
    }
  }, [refresh, runId, state])
}
