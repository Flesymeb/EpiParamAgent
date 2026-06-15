import { createContext, useContext, useEffect } from "react"

// Lets a page publish contextual identity (breadcrumb + status) into the global
// ShellHeader (the top nav bar) without prop-drilling. We pass structured DATA
// (not JSX) and key the publish effect on a derived string so re-renders don't
// thrash the provider state.

export type RunHeaderData = {
  runId: string
  status?: string | null
  stepRunning?: boolean
  paramsSummary: string
}

export type PageHeaderContextValue = {
  header: RunHeaderData | null
  setHeader: (header: RunHeaderData | null) => void
}

export const PageHeaderContext = createContext<PageHeaderContextValue | null>(
  null
)

export function usePageHeader(): RunHeaderData | null {
  return useContext(PageHeaderContext)?.header ?? null
}

export function useSetRunHeader(data: RunHeaderData | null): void {
  const setHeader = useContext(PageHeaderContext)?.setHeader
  const key = data
    ? `${data.runId}|${data.status ?? ""}|${data.stepRunning ? 1 : 0}|${data.paramsSummary}`
    : null

  useEffect(() => {
    setHeader?.(data)
    return () => setHeader?.(null)
    // Keyed on the derived string so identity-only changes don't re-publish.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setHeader, key])
}
