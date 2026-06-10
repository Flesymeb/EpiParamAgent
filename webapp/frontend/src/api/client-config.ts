import type { CreateClientConfig } from "./client/client.gen"
import { API_BASE_URL } from "@/lib/config"

export const createClientConfig: CreateClientConfig = (config) => ({
  ...config,
  baseUrl: API_BASE_URL,
})
