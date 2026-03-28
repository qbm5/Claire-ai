import { get, post } from './api'

export interface DashboardData {
  stats: {
    pipelines: number
    tools: number
    chatbots: number
    triggers: number
    active_runs: number
    active_processes: number
    active_triggers: number
    active_tasks: number
  }
  active_runs: {
    id: string
    pipeline_name: string
    pipeline_id: string
    status: number
    current_step: number
    total_steps: number
    created_at: string
    completed_at: string
    duration_s: number | null
    cost: number
    tool_id?: string
    user_id?: string
    run_type?: string
  }[]
  active_tasks: {
    id: string
    task_plan_id: string
    task_name: string
    request: string
    current_step_name: string
    total_steps: number
    created_at: string
  }[]
  active_triggers: {
    id: string
    name: string
    trigger_type: number
    trigger_type_label: string
    last_fired_at: string
    last_status: string
    fire_count: number
    connections_count: number
  }[]
  processes: {
    pid: number
    command: string
    running: boolean
  }[]
  recent_runs: {
    id: string
    pipeline_name: string
    pipeline_id: string
    status: number
    created_at: string
    completed_at: string
    duration_s: number | null
    cost: number
    tool_id?: string
    user_id?: string
    run_type?: string
    task_plan_id?: string
  }[]
  job_object_active: boolean
}

export const getDashboard = (since?: string, userId?: string) => {
  const params = new URLSearchParams()
  if (since) params.set('since', since)
  if (userId) params.set('user_id', userId)
  const qs = params.toString()
  return get<DashboardData>(`/dashboard${qs ? `?${qs}` : ''}`)
}
export const forceStopRun = (runId: string) => post<{ success: boolean; forced: boolean }>(`/dashboard/runs/${runId}/stop`, {})
export const stopTaskRun = (runId: string) => post<{ success: boolean; forced: boolean }>(`/dashboard/task-runs/${runId}/stop`, {})
export const killProcess = (pid: number) => post<{ success: boolean }>(`/dashboard/processes/${pid}/kill`, {})
