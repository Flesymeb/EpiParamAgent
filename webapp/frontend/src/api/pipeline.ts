import {
  createRunRunsPost,
  getRunRunsRunIdGet,
  getStepRowsRunsRunIdStepsStepNoRowsGet,
  listRunsRunsGet,
  saveEditedStepRunsRunIdStepsStepNoEditedPut,
  startStepRunsRunIdStepsStepNoStartPost,
} from "./client/sdk.gen"
import type {
  CreateRunRequest,
  GetStepRowsRunsRunIdStepsStepNoRowsGetResponse,
  RunDetail as GeneratedRunDetail,
  RunRead,
  SaveEditedStepRequest,
  StartStepResponse,
  StepRead,
} from "./client/types.gen"
import { subscribeToRunEvents } from "./events"
import { getApiBaseUrl } from "@/lib/config"

export type CreateRunParams = NonNullable<CreateRunRequest["params"]>
export type Run = RunRead
export type PipelineStep = StepRead
export type RunDetail = GeneratedRunDetail
export type StartStepResult = StartStepResponse
export type StepRows = GetStepRowsRunsRunIdStepsStepNoRowsGetResponse
export type SaveEditedStepBody = SaveEditedStepRequest

export async function createRun(params: CreateRunParams = {}): Promise<Run> {
  const response = await createRunRunsPost({
    body: { params },
    throwOnError: true,
  })

  return response.data
}

export async function listRuns(): Promise<Run[]> {
  const response = await listRunsRunsGet({ throwOnError: true })

  return response.data
}

export async function getRun(runId: string): Promise<RunDetail> {
  const response = await getRunRunsRunIdGet({
    path: { run_id: runId },
    throwOnError: true,
  })

  return response.data
}

export async function startStep(
  runId: string,
  stepNo: number,
  params?: Record<string, unknown>,
): Promise<StartStepResult> {
  const response = await startStepRunsRunIdStepsStepNoStartPost({
    path: { run_id: runId, step_no: stepNo },
    body: { params: params ?? {} },
    throwOnError: true,
  })

  return response.data
}

export async function getStepRows(
  runId: string,
  stepNo: number,
): Promise<StepRows> {
  const response = await getStepRowsRunsRunIdStepsStepNoRowsGet({
    path: { run_id: runId, step_no: stepNo },
    throwOnError: true,
  })

  return response.data
}

export async function getStepFile(
  runId: string,
  stepNo: number,
  name: string,
): Promise<StepRows> {
  const response = await getStepRowsRunsRunIdStepsStepNoRowsGet({
    path: { run_id: runId, step_no: stepNo },
    query: { name },
    throwOnError: true,
  })

  return response.data
}

/** Aggregated per-paper structured index produced by a coding run (Code stage). */
export async function getStepIndex(
  runId: string,
  stepNo: number,
  signal?: AbortSignal,
): Promise<StepRows> {
  const base = getApiBaseUrl().replace(/\/$/, "")
  const response = await fetch(
    `${base}/runs/${encodeURIComponent(runId)}/steps/${stepNo}/index`,
    { signal },
  )
  if (!response.ok) {
    throw new Error(`Index request failed (${response.status})`)
  }
  return (await response.json()) as StepRows
}

export async function saveEditedStep(
  runId: string,
  stepNo: number,
  body: SaveEditedStepBody,
): Promise<PipelineStep> {
  const response = await saveEditedStepRunsRunIdStepsStepNoEditedPut({
    body,
    path: { run_id: runId, step_no: stepNo },
    throwOnError: true,
  })

  return response.data
}

export function artifactUrl(runId: string, stepNo: number): string {
  return `${getApiBaseUrl()}/runs/${encodeURIComponent(
    runId,
  )}/steps/${stepNo}/artifact`
}

export { subscribeToRunEvents }
export type { RunEvent, SubscribeToRunEventsOptions } from "./events"
