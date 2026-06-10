import { Navigate, Route, Routes, useLocation } from "react-router-dom"

import { AppSidebar } from "@/components/app-sidebar"
import { ThemeProvider } from "@/components/theme-provider"
import { ThemeToggle } from "@/components/theme-toggle"
import { Separator } from "@/components/ui/separator"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { DashboardPage } from "@/pages/dashboard-page"
import { RunDetailPage } from "@/pages/run-detail-page"

function ShellHeader() {
  const { pathname } = useLocation()
  const pageLabel = pathname.startsWith("/runs/") ? "Run detail" : "Runs"

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background/95 px-3 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <SidebarTrigger className="-ml-1" />
      <Separator
        orientation="vertical"
        className="mx-1 data-[orientation=vertical]:h-4"
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{pageLabel}</p>
      </div>
      <ThemeToggle />
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
        <SidebarProvider>
          <AppSidebar />
          <SidebarInset>
            <ShellHeader />
            <main className="flex flex-1 flex-col p-4 md:p-6">
              <Routes>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/runs/:runId" element={<RunDetailPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </main>
          </SidebarInset>
        </SidebarProvider>
        <Toaster position="top-right" />
      </TooltipProvider>
    </ThemeProvider>
  )
}

export default App
