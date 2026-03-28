import type { AiTool, AiPipelineRun, Property, PipResult } from '@/models'
import { get, post, del, wsConnect, uploadFile } from './api'

export type { PipResult }

export function getTools(): Promise<AiTool[]> {
  return get<AiTool[]>('/tools')
}

export function getTool(id: string): Promise<AiTool> {
  return get<AiTool>(`/tools/${id}`)
}

export function saveTool(tool: AiTool): Promise<{ response: string; pip_results?: PipResult[] }> {
  return post<{ response: string; pip_results?: PipResult[] }>('/tools', tool)
}

export function deleteTool(id: string): Promise<void> {
  return del<void>(`/tools/${id}`)
}

export function getSharedFunctions(): Promise<{ response: { name: string; path: string; content: string }[] }> {
  return get('/tools/shared-functions')
}

export function testMcpConnection(config: any): Promise<{ success: boolean; tools?: any[]; error?: string }> {
  return post('/tools/mcp-test', config)
}

export function runTool(toolId: string, inputs: Property[]): Promise<AiPipelineRun> {
  return post<AiPipelineRun>(`/tools/${toolId}/run`, { inputs })
}

export function getToolRuns(toolId: string): Promise<AiPipelineRun[]> {
  return get<AiPipelineRun[]>(`/tools/${toolId}/runs`)
}

export function deleteToolRun(runId: string): Promise<void> {
  return del<void>(`/tools/runs/${runId}`)
}

export function uploadToolImage(toolId: string, file: File): Promise<{ image_url: string }> {
  return uploadFile(`/tools/${toolId}/image`, file)
}

export function deleteToolImage(toolId: string): Promise<{ response: string }> {
  return del<{ response: string }>(`/tools/${toolId}/image`)
}

export interface AiAssistEvent {
  type: 'status' | 'delta' | 'result' | 'error'
  text?: string
  tool_config?: Record<string, any>
  usage?: { model?: string; input_tokens?: number; output_tokens?: number }
}

export function wsAiAssistTool(
  description: string,
  model: string,
  currentTool: AiTool,
  onEvent: (event: AiAssistEvent) => void,
): { promise: Promise<void>; abort: () => void } {
  let ws: WebSocket | null = null
  const promise = new Promise<void>((resolve, reject) => {
    ws = wsConnect('/ai-assist')
    ws.onopen = () => ws!.send(JSON.stringify({ description, model, current_tool: currentTool }))
    ws.onmessage = (e) => onEvent(JSON.parse(e.data))
    ws.onclose = () => resolve()
    ws.onerror = () => reject(new Error('WebSocket error'))
  })
  return {
    promise,
    abort: () => { if (ws) ws.close() },
  }
}

export function wsToolTest(tool: AiTool, onMessage: (data: any) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const ws = wsConnect('/tool-test')
    ws.onopen = () => ws.send(JSON.stringify({ tool }))
    ws.onmessage = (e) => onMessage(JSON.parse(e.data))
    ws.onclose = () => resolve()
    ws.onerror = () => reject(new Error('WebSocket error'))
  })
}
