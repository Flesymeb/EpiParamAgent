import { useSyncExternalStore } from "react"

export type AppSettings = {
  backendUrl: string
  defaultDisease: string
  defaultParameter: string
  proxy: string
  skillsPath: string
  tools: string
}

const SETTINGS_KEY = "metaagent-epi-settings"

export const DEFAULT_SETTINGS: AppSettings = {
  backendUrl: "",
  defaultDisease: "mpox",
  defaultParameter: "serial_interval",
  proxy: "",
  skillsPath: "",
  tools: "",
}

type Listener = () => void

const listeners = new Set<Listener>()

let cachedSettings = readStoredSettings()
let hasStorageListener = false

function normalizeSettings(value: Partial<AppSettings> | null): AppSettings {
  return {
    backendUrl: stringOrDefault(value?.backendUrl, DEFAULT_SETTINGS.backendUrl),
    defaultDisease: stringOrDefault(
      value?.defaultDisease,
      DEFAULT_SETTINGS.defaultDisease
    ),
    defaultParameter: stringOrDefault(
      value?.defaultParameter,
      DEFAULT_SETTINGS.defaultParameter
    ),
    proxy: stringOrDefault(value?.proxy, DEFAULT_SETTINGS.proxy),
    skillsPath: stringOrDefault(value?.skillsPath, DEFAULT_SETTINGS.skillsPath),
    tools: stringOrDefault(value?.tools, DEFAULT_SETTINGS.tools),
  }
}

function stringOrDefault(value: unknown, fallback: string) {
  return typeof value === "string" ? value : fallback
}

function readStoredSettings(): AppSettings {
  if (typeof window === "undefined") {
    return DEFAULT_SETTINGS
  }

  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY)
    if (!raw) {
      return DEFAULT_SETTINGS
    }

    return normalizeSettings(JSON.parse(raw) as Partial<AppSettings>)
  } catch {
    return DEFAULT_SETTINGS
  }
}

function writeStoredSettings(settings: AppSettings) {
  if (typeof window === "undefined") {
    return
  }

  try {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
  } catch {
    // Ignore storage failures; in-memory settings still update for this tab.
  }
}

function settingsEqual(left: AppSettings, right: AppSettings) {
  return (
    left.backendUrl === right.backendUrl &&
    left.defaultDisease === right.defaultDisease &&
    left.defaultParameter === right.defaultParameter &&
    left.proxy === right.proxy &&
    left.skillsPath === right.skillsPath &&
    left.tools === right.tools
  )
}

function updateCachedSettings(nextSettings: AppSettings) {
  if (settingsEqual(cachedSettings, nextSettings)) {
    return
  }

  cachedSettings = nextSettings
  listeners.forEach((listener) => listener())
}

function handleStorage(event: StorageEvent) {
  if (event.key !== SETTINGS_KEY && event.key !== null) {
    return
  }

  updateCachedSettings(readStoredSettings())
}

function ensureStorageListener() {
  if (hasStorageListener || typeof window === "undefined") {
    return
  }

  window.addEventListener("storage", handleStorage)
  hasStorageListener = true
}

function subscribe(listener: Listener) {
  ensureStorageListener()
  listeners.add(listener)

  return () => {
    listeners.delete(listener)
  }
}

function getSnapshot() {
  return cachedSettings
}

export function getSettings(): AppSettings {
  ensureStorageListener()
  return cachedSettings
}

export function setSettings(partial: Partial<AppSettings>) {
  const nextSettings = normalizeSettings({
    ...cachedSettings,
    ...partial,
  })

  if (settingsEqual(cachedSettings, nextSettings)) {
    return
  }

  writeStoredSettings(nextSettings)
  updateCachedSettings(nextSettings)
}

export function resetSettings() {
  if (settingsEqual(cachedSettings, DEFAULT_SETTINGS)) {
    return
  }

  writeStoredSettings(DEFAULT_SETTINGS)
  updateCachedSettings(DEFAULT_SETTINGS)
}

export function useSettings(): {
  settings: AppSettings
  update: (partial: Partial<AppSettings>) => void
  reset: () => void
} {
  const settings = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)

  return {
    settings,
    update: setSettings,
    reset: resetSettings,
  }
}

ensureStorageListener()
