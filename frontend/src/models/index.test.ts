import { describe, it, expect } from 'vitest'
import {
  ToolType, EndpointMethod, PropertyType, PipelineStatusType, TriggerType,
  getUid, createTool, createPipeline, createPipelineStep, createChatBot,
  createTrigger, createPipelineRun, createPipelineMemory,
  ToolTypeLabels, TriggerTypeLabels,
} from './index'

describe('Enums', () => {
  it('ToolType has correct values', () => {
    expect(ToolType.LLM).toBe(0)
    expect(ToolType.Endpoint).toBe(1)
    expect(ToolType.Agent).toBe(3)
    expect(ToolType.Pipeline).toBe(4)
    expect(ToolType.If).toBe(5)
  })

  it('EndpointMethod has correct values', () => {
    expect(EndpointMethod.GET).toBe(0)
    expect(EndpointMethod.POST).toBe(1)
    expect(EndpointMethod.PUT).toBe(2)
    expect(EndpointMethod.DELETE).toBe(3)
  })

  it('PropertyType has correct values', () => {
    expect(PropertyType.TEXT).toBe(0)
    expect(PropertyType.NUMBER).toBe(1)
    expect(PropertyType.BOOLEAN).toBe(2)
    expect(PropertyType.FILE).toBe(3)
    expect(PropertyType.SELECT).toBe(6)
  })

  it('PipelineStatusType has correct values', () => {
    expect(PipelineStatusType.Pending).toBe(0)
    expect(PipelineStatusType.Running).toBe(1)
    expect(PipelineStatusType.Completed).toBe(2)
    expect(PipelineStatusType.Failed).toBe(3)
  })
})

describe('getUid', () => {
  it('returns a string', () => {
    expect(typeof getUid()).toBe('string')
  })

  it('returns unique values', () => {
    const ids = new Set(Array.from({ length: 50 }, () => getUid()))
    expect(ids.size).toBe(50)
  })

  it('respects length parameter', () => {
    const uid = getUid(4)
    // length is base random part + counter suffix, so at least 4 chars
    expect(uid.length).toBeGreaterThanOrEqual(4)
  })
})

describe('createTool', () => {
  it('returns a tool with unique id', () => {
    const tool = createTool()
    expect(tool.id).toBeTruthy()
    expect(tool.name).toContain('Tool')
  })

  it('has correct defaults', () => {
    const tool = createTool()
    expect(tool.type).toBe(ToolType.LLM)
    expect(tool.is_enabled).toBe(true)
    expect(tool.endpoint_method).toBe(EndpointMethod.GET)
    expect(tool.agent_functions).toEqual([])
    expect(tool.pip_dependencies).toEqual([])
    expect(tool.endpoint_timeout).toBe(60)
  })

  it('has default request input', () => {
    const tool = createTool()
    expect(tool.request_inputs.length).toBe(1)
    expect(tool.request_inputs[0].name).toBe('Input')
    expect(tool.request_inputs[0].is_default).toBe(true)
    expect(tool.request_inputs[0].is_required).toBe(true)
  })

  it('creates unique tools', () => {
    const t1 = createTool()
    const t2 = createTool()
    expect(t1.id).not.toBe(t2.id)
  })
})

describe('createPipeline', () => {
  it('returns pipeline with defaults', () => {
    const p = createPipeline()
    expect(p.id).toBeTruthy()
    expect(p.steps).toEqual([])
    expect(p.edges).toEqual([])
    expect(p.memories).toEqual([])
    expect(p.inputs.length).toBe(1)
    expect(p.inputs[0].name).toBe('Start')
  })
})

describe('createPipelineStep', () => {
  it('returns step with defaults', () => {
    const s = createPipelineStep()
    expect(s.id).toBeTruthy()
    expect(s.status).toBe(PipelineStatusType.Pending)
    expect(s.is_start).toBe(false)
    expect(s.disabled).toBe(false)
    expect(s.max_retries).toBe(1)
    expect(s.inputs.length).toBe(1)
  })

  it('has pre/post process defaults', () => {
    const s = createPipelineStep()
    expect(s.pre_process).toContain('function process')
    expect(s.post_process).toContain('function process')
  })
})

describe('createChatBot', () => {
  it('returns chatbot with defaults', () => {
    const bot = createChatBot()
    expect(bot.id).toBeTruthy()
    expect(bot.is_enabled).toBe(true)
    expect(bot.is_deleted).toBe(false)
    expect(bot.source_type).toBe('text')
    expect(bot.github_branch).toBe('main')
  })
})

describe('createTrigger', () => {
  it('returns trigger with defaults', () => {
    const t = createTrigger()
    expect(t.id).toBeTruthy()
    expect(t.is_enabled).toBe(false)
    expect(t.trigger_type).toBe(TriggerType.Cron)
    expect(t.cron_expression).toBe('0 * * * *')
    expect(t.code).toContain('def on_trigger')
  })
})

describe('createPipelineRun', () => {
  it('creates run from pipeline', () => {
    const pipeline = createPipeline()
    const run = createPipelineRun(pipeline)
    expect(run.pipeline_id).toBe(pipeline.id)
    expect(run.status).toBe(PipelineStatusType.Pending)
    expect(run.inputs).toBe(pipeline.inputs)
    expect(run.created_at).toBeTruthy()
  })
})

describe('createPipelineMemory', () => {
  it('creates short term by default', () => {
    const mem = createPipelineMemory()
    expect(mem.type).toBe('short_term')
    expect(mem.max_messages).toBe(0)
    expect(mem.messages).toEqual([])
  })

  it('creates long term', () => {
    const mem = createPipelineMemory('long_term')
    expect(mem.type).toBe('long_term')
    expect(mem.name).toContain('Long Term')
  })
})

describe('Label maps', () => {
  it('ToolTypeLabels covers all types', () => {
    expect(ToolTypeLabels[ToolType.LLM]).toBe('LLM')
    expect(ToolTypeLabels[ToolType.Agent]).toBe('Agent')
    expect(ToolTypeLabels[ToolType.Endpoint]).toBe('Endpoint')
  })

  it('TriggerTypeLabels covers all types', () => {
    expect(TriggerTypeLabels[TriggerType.Cron]).toBe('Cron')
    expect(TriggerTypeLabels[TriggerType.Webhook]).toBe('Webhook')
    expect(TriggerTypeLabels[TriggerType.RSS]).toBe('RSS')
  })
})
