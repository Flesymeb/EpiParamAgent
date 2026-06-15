import { useState } from "react"
import type { ReactNode } from "react"
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom"

import { AppSidebar } from "@/components/app-sidebar"
import { StatusBadge } from "@/components/status-badge"
import { ThemeProvider } from "@/components/theme-provider"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import {
  PageHeaderContext,
  usePageHeader,
} from "@/lib/page-header"
import type { RunHeaderData } from "@/lib/page-header"
import { DashboardPage } from "@/pages/dashboard-page"
import { RunDetailPage } from "@/pages/run-detail-page"

function PageHeaderProvider({ children }: { children: ReactNode }) {
  const [header, setHeader] = useState<RunHeaderData | null>(null)

  return (
    <PageHeaderContext.Provider value={{ header, setHeader }}>
      {children}
    </PageHeaderContext.Provider>
  )
}

function shortRunId(runId: string) {
  return runId.length > 12 ? `${runId.slice(0, 8)}…` : runId
}

function ShellHeader() {
  const { pathname } = useLocation()
  const header = usePageHeader()

  // The home/dashboard owns its own page chrome, so the top bar only appears on
  // run pages, where it carries the run breadcrumb + status.
  if (!pathname.startsWith("/runs/")) {
    return null
  }

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b bg-background/95 px-3 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="flex min-w-0 flex-1 items-center gap-2">
        {header ? (
          <>
            <Link
              className="shrink-0 rounded-md text-sm font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
              to="/"
            >
              Runs
            </Link>
            <span aria-hidden="true" className="text-muted-foreground/40">
              /
            </span>
            <span
              className="shrink-0 font-mono text-sm font-medium"
              title={header.runId}
            >
              {shortRunId(header.runId)}
            </span>
            <StatusBadge status={header.status} />
            {header.stepRunning ? (
              <StatusBadge label="step running" status="running" />
            ) : null}
            <span
              className="min-w-0 flex-1 truncate text-xs text-muted-foreground sm:text-sm"
              title={header.paramsSummary}
            >
              {header.paramsSummary}
            </span>
          </>
        ) : (
          <p className="truncate text-sm font-medium">Run detail</p>
        )}
      </div>
    </header>
  )
}

function App() {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      disableTransitionOnChange
      storageKey="metaagent-epi-theme"
    >
      <TooltipProvider>
        <PageHeaderProvider>
          <SidebarProvider>
            <AppSidebar />
            <SidebarInset>
              <ShellHeader />
              <main className="flex flex-1 flex-col bg-gradient-to-b from-muted/40 to-background p-4 md:p-6 dark:from-muted/15">
                <Routes>
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/runs/:runId" element={<RunDetailPage />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </main>
            </SidebarInset>
          </SidebarProvider>
        </PageHeaderProvider>
        <Toaster position="top-right" />
      </TooltipProvider>
    </ThemeProvider>
  )
}

export default App
