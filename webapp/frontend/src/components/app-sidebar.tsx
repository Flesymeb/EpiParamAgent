import { Link, useLocation } from "react-router-dom"
import type { ComponentProps } from "react"
import { useEffect, useState } from "react"
import type { LucideIcon } from "lucide-react"
import {
  ActivityIcon,
  ListChecksIcon,
  MoonIcon,
  SettingsIcon,
  SunIcon,
} from "lucide-react"
import { useTheme } from "next-themes"

import { SettingsDialog } from "@/components/settings-dialog"
import { Badge } from "@/components/ui/badge"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar"
import { getApiBaseUrl } from "@/lib/config"
import { cn } from "@/lib/utils"

type SidebarNavItem = {
  title: string
  url: string
  icon: LucideIcon
}

const workspaceItems: SidebarNavItem[] = [
  {
    title: "Runs",
    url: "/",
    icon: ListChecksIcon,
  },
]

type BackendStatus = "checking" | "offline" | "reachable"

function SidebarNavGroup({
  label,
  onNavigate,
  items,
}: {
  label: string
  onNavigate: () => void
  items: SidebarNavItem[]
}) {
  const { pathname, search } = useLocation()
  const currentUrl = `${pathname}${search}`

  return (
    <SidebarGroup>
      <SidebarGroupLabel>{label}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => {
            const Icon = item.icon
            const isRoot = item.url === "/"
            const isActive = isRoot
              ? pathname === "/"
              : currentUrl === item.url || pathname === item.url

            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton
                  asChild
                  isActive={isActive}
                  tooltip={item.title}
                >
                  <Link onClick={onNavigate} to={item.url}>
                    <Icon />
                    <span>{item.title}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

export function AppSidebar({
  ...props
}: ComponentProps<typeof Sidebar>) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [backendStatus, setBackendStatus] =
    useState<BackendStatus>("checking")
  const { resolvedTheme, setTheme } = useTheme()
  const { openMobile, setOpenMobile } = useSidebar()
  const { pathname } = useLocation()
  const isDark = resolvedTheme === "dark"

  useEffect(() => {
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => controller.abort(), 2500)

    async function checkBackend() {
      try {
        const response = await fetch(apiPath("/health"), {
          signal: controller.signal,
        })
        setBackendStatus(response.ok ? "reachable" : "offline")
      } catch {
        setBackendStatus("offline")
      } finally {
        window.clearTimeout(timeoutId)
      }
    }

    void checkBackend()

    return () => {
      window.clearTimeout(timeoutId)
      controller.abort()
    }
  }, [])

  const isReachable = backendStatus === "reachable"
  const label =
    backendStatus === "checking"
      ? "API checking"
      : isReachable
        ? "API online"
        : "API offline"
  const apiBaseUrl = getApiBaseUrl()
  const showFloatingMobileTrigger =
    !pathname.startsWith("/runs/") && !settingsOpen && !openMobile
  const closeMobileSidebar = () => setOpenMobile(false)

  return (
    <>
      <Sidebar collapsible="icon" variant="inset" {...props}>
        <SidebarHeader>
          <div className="flex items-center gap-1 group-data-[collapsible=icon]:flex-col">
            <SidebarMenu className="min-w-0 flex-1 group-data-[collapsible=icon]:flex-none">
              <SidebarMenuItem>
                <SidebarMenuButton asChild size="lg" tooltip="MetaAgent">
                  <Link onClick={closeMobileSidebar} to="/">
                    <img
                      alt="MetaAgent logo"
                      className="size-8 shrink-0 object-contain"
                      src="/logo.png"
                    />
                    <div className="grid flex-1 text-left text-sm leading-tight">
                      <span className="truncate font-medium">MetaAgent</span>
                      <span className="truncate text-xs text-muted-foreground">
                        v0.3.0
                      </span>
                    </div>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
            <SidebarTrigger className="size-8 shrink-0" />
          </div>
        </SidebarHeader>
        <SidebarContent>
          <SidebarNavGroup
            label="Workspace"
            onNavigate={closeMobileSidebar}
            items={workspaceItems}
          />
        </SidebarContent>
        <SidebarFooter>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                onClick={() => setTheme(isDark ? "light" : "dark")}
                tooltip="Toggle theme"
              >
                {isDark ? <SunIcon /> : <MoonIcon />}
                <span>{isDark ? "Light mode" : "Dark mode"}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton
                onClick={() => {
                  setOpenMobile(false)
                  setSettingsOpen(true)
                }}
                tooltip="Settings"
              >
                <SettingsIcon />
                <span>Settings</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton tooltip={`${label}: ${apiBaseUrl}`}>
                <ActivityIcon
                  className={cn(
                    isReachable
                      ? "text-emerald-600 dark:text-emerald-300"
                      : "text-muted-foreground"
                  )}
                />
                <span>{label}</span>
                <Badge
                  className={cn(
                    "ml-auto border",
                    isReachable
                      ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                      : "border-border bg-muted text-muted-foreground"
                  )}
                  variant="outline"
                >
                  <span
                    aria-hidden="true"
                    className={cn(
                      "size-1.5 rounded-full",
                      isReachable
                        ? "bg-emerald-500 motion-safe:animate-pulse"
                        : "bg-muted-foreground/45"
                    )}
                  />
                  API
                </Badge>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
      {showFloatingMobileTrigger ? (
        <SidebarTrigger
          aria-label="Open navigation"
          className="fixed bottom-[calc(1rem+env(safe-area-inset-bottom))] right-4 z-40 size-10 rounded-full border border-border/70 bg-background/95 shadow-lg backdrop-blur lg:hidden"
        />
      ) : null}
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </>
  )
}

function apiPath(path: string) {
  return `${getApiBaseUrl().replace(/\/$/, "")}${path}`
}
