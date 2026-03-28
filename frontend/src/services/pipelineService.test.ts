import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('./api', () => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  wsConnect: vi.fn(),
  API_BASE: '/api',
  WS_BASE: 'ws://localhost:5173/ws',
}))

import {
  getPipelines, getPipeline, savePipeline, copyPipeline,
  deletePipeline, runPipeline, getPipelineRuns, deletePipelineRun,
  stopPipelineRun, resumePipelineRun, rerunFromStep,
  updateStepOutput,
} from './pipelineService'
import { get, post, put, del } from './api'
import type { AiPipeline, AiPipelineRun } from '@/models'

describe('pipelineService', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('getPipelines calls GET /pipelines', async () => {
    vi.mocked(get).mockResolvedValue([])
    await getPipelines()
    expect(get).toHaveBeenCalledWith('/pipelines')
  })

  it('getPipeline calls GET /pipelines/:id', async () => {
    vi.mocked(get).mockResolvedValue({ id: 'p1' })
    await getPipeline('p1')
    expect(get).toHaveBeenCalledWith('/pipelines/p1')
  })

  it('savePipeline calls POST /pipelines', async () => {
    vi.mocked(post).mockResolvedValue({ response: 'p1' })
    const pipeline = { id: 'p1' } as AiPipeline
    await savePipeline(pipeline)
    expect(post).toHaveBeenCalledWith('/pipelines', pipeline)
  })

  it('copyPipeline calls POST /pipelines/:id/copy', async () => {
    vi.mocked(post).mockResolvedValue({ response: 'p2' })
    await copyPipeline('p1')
    expect(post).toHaveBeenCalledWith('/pipelines/p1/copy', {})
  })

  it('deletePipeline calls DELETE /pipelines/:id', async () => {
    vi.mocked(del).mockResolvedValue(undefined)
    await deletePipeline('p1')
    expect(del).toHaveBeenCalledWith('/pipelines/p1')
  })

  it('runPipeline calls POST /pipelines/run', async () => {
    vi.mocked(post).mockResolvedValue({})
    const run = { id: 'r1' } as AiPipelineRun
    await runPipeline(run)
    expect(post).toHaveBeenCalledWith('/pipelines/run', run)
  })

  it('stopPipelineRun calls POST /pipelines/runs/:id/stop', async () => {
    vi.mocked(post).mockResolvedValue(undefined)
    await stopPipelineRun('r1')
    expect(post).toHaveBeenCalledWith('/pipelines/runs/r1/stop', {})
  })

  it('getPipelineRuns calls GET /pipelines/:id/runs', async () => {
    vi.mocked(get).mockResolvedValue([])
    await getPipelineRuns('p1')
    expect(get).toHaveBeenCalledWith('/pipelines/p1/runs')
  })

  it('resumePipelineRun calls POST /pipelines/runs/:id/resume', async () => {
    vi.mocked(post).mockResolvedValue({})
    await resumePipelineRun('r1')
    expect(post).toHaveBeenCalledWith('/pipelines/runs/r1/resume', {})
  })

  it('rerunFromStep calls POST /pipelines/runs/:id/rerun', async () => {
    vi.mocked(post).mockResolvedValue({})
    await rerunFromStep('r1', 's1')
    expect(post).toHaveBeenCalledWith('/pipelines/runs/r1/rerun', { from_step_id: 's1' })
  })

  it('deletePipelineRun calls DELETE /pipelines/runs/:id', async () => {
    vi.mocked(del).mockResolvedValue(undefined)
    await deletePipelineRun('r1')
    expect(del).toHaveBeenCalledWith('/pipelines/runs/r1')
  })

  it('updateStepOutput calls PUT', async () => {
    vi.mocked(put).mockResolvedValue({ success: true })
    await updateStepOutput('r1', 's1', 'new value')
    expect(put).toHaveBeenCalledWith('/pipelines/runs/r1/steps/s1/output', { value: 'new value' })
  })
})
