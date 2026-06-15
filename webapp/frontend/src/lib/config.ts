import { getSettings } from "@/lib/settings"

export function getApiBaseUrl(): string {
  const override = getSettings().backendUrl?.trim()
  if (override) {
    return override
  }

  return import.meta.env.VITE_API_BASE_URL ?? "/api"
}

export const API_BASE_URL = getApiBaseUrl()

export const DEV_PROXY_TARGET = "http://127.0.0.1:8000"
