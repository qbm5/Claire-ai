import { describe, it, expect, vi } from 'vitest'

// Mock vue-flow to avoid DOM issues in happy-dom
vi.mock('@vue-flow/core', () => ({
  Handle: { template: '<div />' },
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
}))

import { mount } from '@vue/test-utils'
import { ToolType, PipelineStatusType, type AiPipelineStep } from '@/models'

function makeStep(overrides?: Partial<AiPipelineStep>): AiPipelineStep {
  return {
    id: 's1',
    name: 'Test Step',
    description: '',
    next_steps: [],
    next_steps_true: [],
    next_steps_false: [],
    is_start: false,
    tool_id: '-1',
    tool: { id: '-1', name: 'Base LLM', type: ToolType.LLM } as any,
    status: PipelineStatusType.Pending,
    inputs: [],
    outputs: [],
    call_cost: [],
    status_text: '',
    pre_process: '',
    post_process: '',
    disabled: false,
    tool_outputs: [],
    pause_after: false,
    retry_enabled: false,
    validation_enabled: false,
    validation_model: '',
    max_retries: 1,
    memory_id: '',
    pos_x: 0,
    pos_y: 0,
    ...overrides,
  }
}

describe('StepNode', () => {
  it('renders step name', async () => {
    const StepNode = (await import('./StepNode.vue')).default
    const wrapper = mount(StepNode, {
      props: { data: makeStep({ name: 'My LLM Step' }) },
    })
    expect(wrapper.text()).toContain('My LLM Step')
  })

  it('renders LLM type label', async () => {
    const StepNode = (await import('./StepNode.vue')).default
    const wrapper = mount(StepNode, {
      props: { data: makeStep({ tool: { type: ToolType.LLM } as any }) },
    })
    expect(wrapper.text()).toContain('LLM')
  })

  it('renders tool name in normal step', async () => {
    const StepNode = (await import('./StepNode.vue')).default
    const wrapper = mount(StepNode, {
      props: { data: makeStep({ tool: { id: '-1', name: 'Custom Tool', type: ToolType.Endpoint } as any }) },
    })
    expect(wrapper.text()).toContain('Custom Tool')
    expect(wrapper.text()).toContain('Endpoint')
  })

  it('shows disabled state', async () => {
    const StepNode = (await import('./StepNode.vue')).default
    const wrapper = mount(StepNode, {
      props: { data: makeStep({ disabled: true }) },
    })
    // Disabled steps should still render
    expect(wrapper.text()).toContain('Test Step')
  })
})
