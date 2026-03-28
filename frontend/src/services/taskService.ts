import type { TaskPlan, TaskRun, TaskPlanStep } from '@/models'
import { get, post, del, wsConnect } from './api'

export function getTaskPlans(): Promise<TaskPlan[]> {
  return get<TaskPlan[]>('/tasks')
}

export function getTaskPlan(id: string): Promise<TaskPlan> {
  return get<TaskPlan>(`/tasks/${id}`)
}

export function saveTaskPlan(plan: TaskPlan): Promise<{ response: string }> {
  return post<{ response: string }>('/tasks', plan)
}

export function deleteTaskPlan(id: string): Promise<void> {
  return del<void>(`/tasks/${id}`)
}

export function getTaskRuns(planId: string): Promise<TaskRun[]> {
  return get<TaskRun[]>(`/tasks/${planId}/runs`)
}

export function deleteTaskRun(runId: string): Promise<void> {
  return del<void>(`/tasks/runs/${runId}`)
}

export function getTaskRun(runId: string): Promise<TaskRun> {
  return get<TaskRun>(`/tasks/runs/${runId}/detail`)
}

export interface StepCost {
  detail: string
  model: string
  input_tokens: number
  output_tokens: number
  input_cost: number
  output_cost: number
  total_cost: number
}

export interface TotalCost {
  input_tokens: number
  output_tokens: number
  total_cost: number
  steps: StepCost[]
}

export interface TaskExecuteEvent {
  type: 'status' | 'plan' | 'step_start' | 'step_delta' | 'step_complete' | 'step_error'
    | 'step_tool_call' | 'step_tool_result' | 'ask_user' | 'complete' | 'error'
    | 'awaiting_approval' | 'step_skipped' | 'step_unskipped' | 'processes'
  text?: string
  plan?: { goal?: string; steps: TaskPlanStep[] }
  planning_cost?: StepCost
  step_id?: string
  name?: string
  output?: string
  error?: string
  run_id?: string
  questions?: { id: string; text: string; type?: string; options?: string[] }[]
  input?: Record<string, any>
  result?: string
  cost?: StepCost
  duration_s?: number
  model?: string
  processes?: { pid: number; command: string; running: boolean }[]
  total_cost?: TotalCost
}

export function wsTaskExecute(
  request: string,
  model: string,
  taskPlanId: string,
  inputValues: Record<string, any>,
  savedPlan: TaskPlanStep[] | null,
  autoRun: boolean,
  onEvent: (event: TaskExecuteEvent) => void,
): {
  promise: Promise<void>
  abort: () => void
  sendAnswer: (stepId: string, answers: { id: string; answer: string }[]) => void
  approve: () => void
  skipStep: (stepId: string) => void
  unskipStep: (stepId: string) => void
  setStepModel: (stepId: string, model: string) => void
} {
  let ws: WebSocket | null = null
  const promise = new Promise<void>((resolve, reject) => {
    ws = wsConnect('/task-execute')
    ws.onopen = () => {
      const payload: Record<string, any> = {
        request, model, task_plan_id: taskPlanId,
        input_values: inputValues, auto_run: autoRun,
      }
      if (savedPlan) payload.saved_plan = savedPlan
      ws!.send(JSON.stringify(payload))
    }
    ws.onmessage = (e) => onEvent(JSON.parse(e.data))
    ws.onclose = () => resolve()
    ws.onerror = () => reject(new Error('WebSocket error'))
  })
  return {
    promise,
    abort: () => { if (ws) ws.close() },
    sendAnswer: (stepId, answers) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'answer', step_id: stepId, answers }))
      }
    },
    approve: () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'approve' }))
      }
    },
    skipStep: (stepId) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'skip_step', step_id: stepId }))
      }
    },
    unskipStep: (stepId) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'unskip_step', step_id: stepId }))
      }
    },
    setStepModel: (stepId, model) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'set_step_model', step_id: stepId, model }))
      }
    },
  }
}
