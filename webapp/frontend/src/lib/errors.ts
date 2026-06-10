export function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message
  }

  if (typeof error === "string" && error) {
    return error
  }

  if (isRecord(error)) {
    const detail = error.detail
    if (typeof detail === "string" && detail) {
      return detail
    }

    const message = error.message
    if (typeof message === "string" && message) {
      return message
    }
  }

  return "Unexpected API error"
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}
