import { defineConfig } from "@hey-api/openapi-ts"

export default defineConfig({
  input: "http://127.0.0.1:8000/openapi.json",
  output: {
    path: "src/api/client",
    clean: true,
  },
  plugins: [
    {
      name: "@hey-api/client-fetch",
      baseUrl: false,
      runtimeConfigPath: "./src/api/client-config.ts",
    },
    "@hey-api/typescript",
    "@hey-api/sdk",
  ],
})
