import type { AiTrigger, PipResult } from '@/models'
import { get, post, del, wsConnect, uploadFile } from './api'

export type { PipResult }

export function getTriggers(): Promise<AiTrigger[]> {
  return get<AiTrigger[]>('/triggers')
}

export function getTrigger(id: string): Promise<AiTrigger> {
  return get<AiTrigger>(`/triggers/${id}`)
}

export function saveTrigger(trigger: AiTrigger): Promise<{ response: string; pip_results?: PipResult[] }> {
  return post<{ response: string; pip_results?: PipResult[] }>('/triggers', trigger)
}

export function deleteTrigger(id: string): Promise<void> {
  return del<void>(`/triggers/${id}`)
}

export function uploadTriggerImage(triggerId: string, file: File): Promise<{ image_url: string }> {
  return uploadFile(`/triggers/${triggerId}/image`, file)
}

export function deleteTriggerImage(triggerId: string): Promise<{ response: string }> {
  return del<{ response: string }>(`/triggers/${triggerId}/image`)
}

export function fireTrigger(id: string): Promise<any> {
  return post<any>(`/triggers/${id}/fire`, {})
}

export interface TriggerAiAssistEvent {
  type: 'status' | 'delta' | 'result' | 'error'
  text?: string
  trigger_config?: Record<string, any>
  usage?: { model?: string; input_tokens?: number; output_tokens?: number }
}

export function wsAiAssistTrigger(
  description: string,
  model: string,
  currentTrigger: AiTrigger,
  onEvent: (event: TriggerAiAssistEvent) => void,
): { promise: Promise<void>; abort: () => void } {
  let ws: WebSocket | null = null
  const promise = new Promise<void>((resolve, reject) => {
    ws = wsConnect('/ai-assist-trigger')
    ws.onopen = () => ws!.send(JSON.stringify({ description, model, current_trigger: currentTrigger }))
    ws.onmessage = (e) => onEvent(JSON.parse(e.data))
    ws.onclose = () => resolve()
    ws.onerror = () => reject(new Error('WebSocket error'))
  })
  return {
    promise,
    abort: () => { if (ws) ws.close() },
  }
}
