import { describe, it, expect } from 'vitest'
import {
  validateToolImport,
  validateTriggerImport,
  validatePipelineImport,
  validateImport,
} from './importValidator'

describe('importValidator', () => {
  // ── Tool ────────────────────────────────────────────────────

  describe('validateToolImport', () => {
    const validTool = {
      _export_type: 'tool',
      name: 'Test Tool',
      type: 0,
      is_enabled: true,
      description: 'A test tool',
      prompt: '{{Input}}',
      system_prompt: '',
      model: 'claude-sonnet-4-20250514',
      request_inputs: [{ name: 'Input', value: '', type: 0 }],
      agent_functions: [],
      env_variables: [],
      mcp_servers: [],
      export_uid: 'abc123',
      export_version: 1,
    }

    it('accepts a valid tool', () => {
      const result = validateToolImport(validTool)
      expect(result.valid).toBe(true)
      expect(result.errors).toHaveLength(0)
    })

    it('rejects missing _export_type', () => {
      const { _export_type, ...data } = validTool
      const result = validateToolImport(data)
      expect(result.valid).toBe(false)
      expect(result.errors.some(e => e.path === '_export_type')).toBe(true)
    })

    it('rejects wrong _export_type', () => {
      const result = validateToolImport({ ...validTool, _export_type: 'pipeline' })
      expect(result.valid).toBe(false)
      expect(result.errors.some(e => e.path === '_export_type')).toBe(true)
    })

    it('rejects missing name', () => {
      const { name, ...data } = validTool
      const result = validateToolImport(data)
      expect(result.valid).toBe(false)
      expect(result.errors.some(e => e.path === 'name')).toBe(true)
    })

    it('rejects missing type', () => {
      const { type, ...data } = validTool
      const result = validateToolImport(data)
      expect(result.valid).toBe(false)
      expect(result.errors.some(e => e.path === 'type')).toBe(true)
    })

    it('rejects invalid tool type', () => {
      const result = validateToolImport({ ...validTool, type: 99 })
      expect(result.valid).toBe(false)
      expect(result.errors.some(e => e.path === 'type')).toBe(true)
    })

    it('rejects non-object input', () => {
      expect(validateToolImport('string').valid).toBe(false)
      expect(validateToolImport(42).valid).toBe(false)
      expect(validateToolImport(null).valid).toBe(false)
      expect(validateToolImport([]).valid).toBe(false)
    })

    it('validates agent_functions items', () => {
      const result = validateToolImport({
        ...validTool,
        agent_functions: [{ uid: 'a', name: 'fn', function_string: 'def fn(): pass' }],
      })
      expect(result.valid).toBe(true)
    })

    it('rejects agent function missing uid', () => {
      const result = validateToolImport({
        ...validTool,
        agent_functions: [{ name: 'fn', function_string: 'def fn(): pass' }],
      })
      expect(result.valid).toBe(false)
      expect(result.errors.some(e => e.path.includes('agent_functions[0]'))).toBe(true)
    })

    it('validates env_variables items', () => {
      const result = validateToolImport({
        ...validTool,
        env_variables: [{ name: 'API_KEY', description: 'Key', type: 5 }],
      })
      expect(result.valid).toBe(true)
    })

    it('validates mcp_servers items', () => {
      const result = validateToolImport({
        ...validTool,
        mcp_servers: [{ uid: 's1', name: 'Server', transport: 1, url: 'http://localhost' }],
      })
      expect(result.valid).toBe(true)
    })

    it('rejects mcp_server with invalid transport', () => {
      const result = validateToolImport({
        ...validTool,
        mcp_servers: [{ uid: 's1', name: 'Server', transport: 5 }],
      })
      expect(result.valid).toBe(false)
    })

    it('accepts all valid tool types', () => {
      for (const t of [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14]) {
        const result = validateToolImport({ ...validTool, type: t })
        expect(result.valid).toBe(true)
      }
    })
  })

  // ── Trigger ─────────────────────────────────────────────────

  describe('validateTriggerImport', () => {
    const validTrigger = {
      _export_type: 'trigger',
      name: 'Test Trigger',
      trigger_type: 0,
      is_enabled: false,
      cron_expression: '0 * * * *',
      code: 'def on_trigger(ctx): return ctx',
      outputs: [],
      connections: [],
      env_variables: [],
      export_uid: 'tr123',
      export_version: 1,
    }

    it('accepts a valid trigger', () => {
      const result = validateTriggerImport(validTrigger)
      expect(result.valid).toBe(true)
    })

    it('rejects wrong _export_type', () => {
      const result = validateTriggerImport({ ...validTrigger, _export_type: 'tool' })
      expect(result.valid).toBe(false)
    })

    it('rejects missing name', () => {
      const { name, ...data } = validTrigger
      const result = validateTriggerImport(data)
      expect(result.valid).toBe(false)
    })

    it('rejects invalid trigger_type', () => {
      const result = validateTriggerImport({ ...validTrigger, trigger_type: 99 })
      expect(result.valid).toBe(false)
    })

    it('accepts all valid trigger types', () => {
      for (const t of [0, 1, 2, 3, 4]) {
        const result = validateTriggerImport({ ...validTrigger, trigger_type: t })
        expect(result.valid).toBe(true)
      }
    })

    it('validates connections', () => {
      const result = validateTriggerImport({
        ...validTrigger,
        connections: [{ id: 'c1', pipeline_id: 'p1', pipeline_name: 'Test', is_enabled: true }],
      })
      expect(result.valid).toBe(true)
    })

    it('rejects connection missing id', () => {
      const result = validateTriggerImport({
        ...validTrigger,
        connections: [{ pipeline_id: 'p1' }],
      })
      expect(result.valid).toBe(false)
    })
  })

  // ── Pipeline ────────────────────────────────────────────────

  describe('validatePipelineImport', () => {
    const validPipeline = {
      _export_type: 'pipeline',
      name: 'Test Pipeline',
      description: 'A test',
      steps: [
        { id: 's1', name: 'Start', tool_id: '-9', tool: { type: 9, name: 'Start' }, next_steps: ['s2'] },
        { id: 's2', name: 'LLM Step', tool_id: '-1', tool: { type: 0, name: 'LLM' }, next_steps: [] },
      ],
      edges: [{ id: 'e1', source: 's1', target: 's2' }],
      inputs: [{ name: 'Start', value: '' }],
      memories: [],
      export_uid: 'pl123',
      export_version: 1,
    }

    it('accepts a valid pipeline', () => {
      const result = validatePipelineImport(validPipeline)
      expect(result.valid).toBe(true)
    })

    it('rejects wrong _export_type', () => {
      const result = validatePipelineImport({ ...validPipeline, _export_type: 'tool' })
      expect(result.valid).toBe(false)
    })

    it('rejects missing name', () => {
      const { name, ...data } = validPipeline
      const result = validatePipelineImport(data)
      expect(result.valid).toBe(false)
    })

    it('rejects missing steps', () => {
      const { steps, ...data } = validPipeline
      const result = validatePipelineImport(data)
      expect(result.valid).toBe(false)
    })

    it('rejects empty steps array', () => {
      const result = validatePipelineImport({ ...validPipeline, steps: [] })
      expect(result.valid).toBe(false)
      expect(result.errors.some(e => e.path === 'steps' && e.message.includes('at least 1'))).toBe(true)
    })

    it('rejects step missing id', () => {
      const result = validatePipelineImport({
        ...validPipeline,
        steps: [{ name: 'Bad Step' }],
      })
      expect(result.valid).toBe(false)
      expect(result.errors.some(e => e.path.includes('steps[0]'))).toBe(true)
    })

    it('rejects step missing name', () => {
      const result = validatePipelineImport({
        ...validPipeline,
        steps: [{ id: 's1' }],
      })
      expect(result.valid).toBe(false)
    })

    it('validates embedded _tools', () => {
      const result = validatePipelineImport({
        ...validPipeline,
        _tools: [{ name: 'Agent Tool', type: 3, id: 'abc' }],
      })
      expect(result.valid).toBe(true)
    })

    it('rejects _tools item missing name', () => {
      const result = validatePipelineImport({
        ...validPipeline,
        _tools: [{ type: 3 }],
      })
      expect(result.valid).toBe(false)
    })

    it('validates memories', () => {
      const result = validatePipelineImport({
        ...validPipeline,
        memories: [{ id: 'm1', name: 'Short Term Memory', type: 'short_term' }],
      })
      expect(result.valid).toBe(true)
    })

    it('rejects memory with invalid type', () => {
      const result = validatePipelineImport({
        ...validPipeline,
        memories: [{ id: 'm1', name: 'Bad', type: 'invalid' }],
      })
      expect(result.valid).toBe(false)
    })

    it('validates edges', () => {
      const result = validatePipelineImport({
        ...validPipeline,
        edges: [{ id: 'e1', source: 's1', target: 's2' }],
      })
      expect(result.valid).toBe(true)
    })

    it('rejects edge missing source', () => {
      const result = validatePipelineImport({
        ...validPipeline,
        edges: [{ id: 'e1', target: 's2' }],
      })
      expect(result.valid).toBe(false)
    })
  })

  // ── Auto-detect ─────────────────────────────────────────────

  describe('validateImport', () => {
    it('detects tool type', () => {
      const result = validateImport({ _export_type: 'tool', name: 'T', type: 0 })
      expect(result.detectedType).toBe('tool')
      expect(result.valid).toBe(true)
    })

    it('detects pipeline type', () => {
      const result = validateImport({
        _export_type: 'pipeline', name: 'P',
        steps: [{ id: 's', name: 'S' }],
      })
      expect(result.detectedType).toBe('pipeline')
      expect(result.valid).toBe(true)
    })

    it('detects trigger type', () => {
      const result = validateImport({ _export_type: 'trigger', name: 'T', trigger_type: 0 })
      expect(result.detectedType).toBe('trigger')
      expect(result.valid).toBe(true)
    })

    it('rejects unknown type', () => {
      const result = validateImport({ _export_type: 'widget', name: 'W' })
      expect(result.valid).toBe(false)
      expect(result.detectedType).toBe('widget')
    })

    it('rejects missing _export_type', () => {
      const result = validateImport({ name: 'No Type' })
      expect(result.valid).toBe(false)
    })

    it('rejects non-object input', () => {
      expect(validateImport(null).valid).toBe(false)
      expect(validateImport('hello').valid).toBe(false)
      expect(validateImport([1, 2]).valid).toBe(false)
    })
  })
})
