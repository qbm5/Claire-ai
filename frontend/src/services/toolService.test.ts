import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the api module
vi.mock('./api', () => ({
  get: vi.fn(),
  post: vi.fn(),
  del: vi.fn(),
  wsConnect: vi.fn(),
  API_BASE: '/api',
  WS_BASE: 'ws://localhost:5173/ws',
}))

import { getTools, getTool, saveTool, deleteTool, runTool, getToolRuns, deleteToolRun } from './toolService'
import { get, post, del } from './api'
import type { AiTool } from '@/models'

describe('toolService', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('getTools calls GET /tools', async () => {
    vi.mocked(get).mockResolvedValue([])
    await getTools()
    expect(get).toHaveBeenCalledWith('/tools')
  })

  it('getTool calls GET /tools/:id', async () => {
    vi.mocked(get).mockResolvedValue({ id: 't1' })
    await getTool('t1')
    expect(get).toHaveBeenCalledWith('/tools/t1')
  })

  it('saveTool calls POST /tools', async () => {
    vi.mocked(post).mockResolvedValue({ response: 't1' })
    const tool = { id: 't1', name: 'Test' } as AiTool
    await saveTool(tool)
    expect(post).toHaveBeenCalledWith('/tools', tool)
  })

  it('deleteTool calls DELETE /tools/:id', async () => {
    vi.mocked(del).mockResolvedValue(undefined)
    await deleteTool('t1')
    expect(del).toHaveBeenCalledWith('/tools/t1')
  })

  it('runTool calls POST /tools/:id/run', async () => {
    vi.mocked(post).mockResolvedValue({})
    const inputs = [{ name: 'Input', value: 'test' }]
    await runTool('t1', inputs)
    expect(post).toHaveBeenCalledWith('/tools/t1/run', { inputs })
  })

  it('getToolRuns calls GET /tools/:id/runs', async () => {
    vi.mocked(get).mockResolvedValue([])
    await getToolRuns('t1')
    expect(get).toHaveBeenCalledWith('/tools/t1/runs')
  })

  it('deleteToolRun calls DELETE /tools/runs/:id', async () => {
    vi.mocked(del).mockResolvedValue(undefined)
    await deleteToolRun('r1')
    expect(del).toHaveBeenCalledWith('/tools/runs/r1')
  })
})
