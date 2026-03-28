import type { AiPipeline, AiPipelineRun } from '@/models'
import { get, post, put, del, wsConnect, uploadFile } from './api'

export function getPipelines(): Promise<AiPipeline[]> {
  return get<AiPipeline[]>('/pipelines')
}

export function getPipeline(id: string): Promise<AiPipeline> {
  return get<AiPipeline>(`/pipelines/${id}`)
}

export function savePipeline(pipeline: AiPipeline): Promise<{ response: string }> {
  return post<{ response: string }>('/pipelines', pipeline)
}

export function copyPipeline(id: string): Promise<{ response: string }> {
  return post<{ response: string }>(`/pipelines/${id}/copy`, {})
}

export function deletePipeline(id: string): Promise<void> {
  return del<void>(`/pipelines/${id}`)
}

export function uploadPipelineImage(pipelineId: string, file: File): Promise<{ image_url: string }> {
  return uploadFile(`/pipelines/${pipelineId}/image`, file)
}

export function deletePipelineImage(pipelineId: string): Promise<{ response: string }> {
  return del<{ response: string }>(`/pipelines/${pipelineId}/image`)
}

export function runPipeline(plRun: AiPipelineRun): Promise<AiPipelineRun> {
  return post<AiPipelineRun>('/pipelines/run', plRun)
}

export function stopPipelineRun(runId: string): Promise<void> {
  return post<void>(`/pipelines/runs/${runId}/stop`, {})
}

export function getPipelineRuns(pipelineId: string): Promise<AiPipelineRun[]> {
  return get<AiPipelineRun[]>(`/pipelines/${pipelineId}/runs`)
}

export function resumePipelineRun(runId: string): Promise<AiPipelineRun> {
  return post<AiPipelineRun>(`/pipelines/runs/${runId}/resume`, {})
}

export function rerunFromStep(runId: string, fromStepId: string): Promise<AiPipelineRun> {
  return post<AiPipelineRun>(`/pipelines/runs/${runId}/rerun`, { from_step_id: fromStepId })
}

export function respondToStep(runId: string, stepId: string, answers: { id: string; answer: string }[]) {
  return post(`/pipelines/runs/${runId}/respond`, { step_id: stepId, answers })
}

export function deletePipelineRun(runId: string): Promise<void> {
  return del<void>(`/pipelines/runs/${runId}`)
}

export function updateStepOutput(runId: string, stepId: string, value: string): Promise<{ success: boolean }> {
  return put<{ success: boolean }>(`/pipelines/runs/${runId}/steps/${stepId}/output`, { value })
}

export interface ClarifyQuestion {
  id: string
  text: string
  type: 'text' | 'choice'
  options?: string[]
}

export interface PipelineAiAssistEvent {
  type: 'status' | 'delta' | 'result' | 'error' | 'questions'
  text?: string
  pipeline_config?: Record<string, any>
  usage?: { model?: string; input_tokens?: number; output_tokens?: number }
  questions?: ClarifyQuestion[]
}

export function wsAiAssistPipeline(
  description: string,
  model: string,
  currentPipeline: AiPipeline,
  onEvent: (event: PipelineAiAssistEvent) => void,
  phase: 'generate' | 'clarify' = 'generate',
): { promise: Promise<void>; abort: () => void; sendAnswers: (answers: { id: string; answer: string }[]) => void } {
  let ws: WebSocket | null = null
  const promise = new Promise<void>((resolve, reject) => {
    ws = wsConnect('/ai-assist-pipeline')
    ws.onopen = () => ws!.send(JSON.stringify({ description, model, current_pipeline: currentPipeline, phase }))
    ws.onmessage = (e) => onEvent(JSON.parse(e.data))
    ws.onclose = () => resolve()
    ws.onerror = () => reject(new Error('WebSocket error'))
  })
  return {
    promise,
    abort: () => { if (ws) ws.close() },
    sendAnswers: (answers) => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ answers })) },
  }
}
