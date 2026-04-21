<script setup lang="ts">
import { ref, onMounted, computed, markRaw, watch, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { VueFlow, useVueFlow, type Node, type Edge, Position } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { PathFindingEdge } from '@vue-flow/pathfinding-edge'
import { getPipeline, savePipeline, runPipeline as apiRunPipeline, getPipelineRuns, deletePipelineRun, deletePipeline as apiDeletePipeline, wsAiAssistPipeline, uploadPipelineImage, deletePipelineImage } from '@/services/pipelineService'
import type { PipelineAiAssistEvent, ClarifyQuestion } from '@/services/pipelineService'
import { getTools, saveTool } from '@/services/toolService'
import { imageUrlToBase64 } from '@/services/api'
import {
  createPipeline, createPipelineStep, createPipelineRun, createPipelineMemory, createTool,
  ToolType, ToolTypeLabels, PipelineStatusType, EndpointMethod,
  getUid, PropertyType, BASE_TOOL_ID, getBaseToolDefaults, getBaseToolPrefix,
  type AiPipeline, type AiPipelineStep, type AiPipelineRun, type AiPipelineMemory, type AiTool, type Property, type ResponseField
} from '@/models'
import { parseKv, serializeKv } from '@/utils/kv'
import { deepClone } from '@/utils/clone'
import { useImageUpload } from '@/composables/useImageUpload'
import { useModels, loadModels } from '@/composables/useModels'
import ModelSelectDropdown from '@/components/shared/ModelSelectDropdown.vue'
import { useToast } from '@/composables/useToast'
import StepNode from '@/components/pipeline/StepNode.vue'
import MemoryNode from '@/components/pipeline/MemoryNode.vue'

const { models } = useModels()
const { show: toast } = useToast()
import { useAuth } from '@/composables/useAuth'
const auth = useAuth()
import InputsNode from '@/components/pipeline/InputsNode.vue'
import DynamicInput from '@/components/shared/DynamicInput.vue'
import InputConfigModal from '@/components/shared/InputConfigModal.vue'
import TemplateInput from '@/components/shared/TemplateInput.vue'
import KeyValueEditor from '@/components/shared/KeyValueEditor.vue'
import CodeEditor from '@/components/CodeEditor.vue'
import ExportModal from '@/components/shared/ExportModal.vue'
import LetterAvatar from '@/components/shared/LetterAvatar.vue'
import ToolSelectDropdown from '@/components/shared/ToolSelectDropdown.vue'
import ResponseStructureEditor from '@/components/shared/ResponseStructureEditor.vue'

const ASK_USER_SYSTEM_PROMPT = `You are a clarification assistant in a pipeline workflow. Your job is to analyze the incoming context and decide whether you need to ask the user clarifying questions before proceeding.

You MUST respond with valid JSON in one of two formats:

1. If you need clarification:
{
  "status": "questions",
  "questions": [
    {
      "id": "q1",
      "text": "Your question here?",
      "type": "choice",
      "options": ["Option A", "Option B", "Option C"]
    },
    {
      "id": "q2",
      "text": "Your open-ended question here?",
      "type": "text"
    }
  ]
}

2. If no clarification is needed (the context is clear and specific enough):
{
  "status": "ready",
  "summary": "A comprehensive summary of the context including any user answers from previous rounds..."
}

Guidelines:
- Use "choice" type when the answer is one of several known options
- Use "text" type for open-ended questions
- Keep questions concise and relevant
- Ask at most 3-4 questions per round
- After receiving user answers, either ask follow-up questions or output "ready" with a comprehensive summary that includes the original context plus all clarifications
- If the input is already clear and specific, respond immediately with "ready"`

const props = defineProps<{ id: string }>()
const router = useRouter()
const route = useRoute()

const pipeline = ref<AiPipeline>(createPipeline())
const tools = ref<AiTool[]>([])
const loading = ref(false)
const selectedStep = ref<AiPipelineStep | null>(null)
const selectedMemory = ref<AiPipelineMemory | null>(null)
const propertiesTab = ref('inputs')
const selectedEdge = ref<string | null>(null)
const pipelineRuns = ref<AiPipelineRun[]>([])
const showRunModal = ref(false)
const runInputs = ref<{ name: string; value: any; type?: number; data?: any }[]>([])
const showInputConfig = ref(false)
const configInput = ref<any>(null)


const showExportModal = ref(false)


const { imageFileInput, uploadingImage, onImageSelected: _onImageSelected, removeImage: _removeImage } = useImageUpload(uploadPipelineImage, deletePipelineImage)
function onImageSelected(event: Event) { _onImageSelected(event, pipeline.value.id, (url) => { pipeline.value.image_url = url }) }
function removeImage() { _removeImage(pipeline.value.id, () => { pipeline.value.image_url = '' }) }


const showAiAssist = ref(false)
const aiAssistModel = ref('')
const aiAssistDescription = ref('')
const aiAssistLoading = ref(false)
const aiAssistStatus = ref('')
const aiAssistStreamJson = ref('')
const aiAssistResult = ref<Record<string, any> | null>(null)
const aiAssistAbort = ref<(() => void) | null>(null)
const aiAssistUsage = ref<{ input_tokens: number; output_tokens: number; cost: number } | null>(null)
const aiAssistQuestions = ref<ClarifyQuestion[]>([])
const aiAssistAnswers = ref<Record<string, string>>({})
const aiAssistPhase = ref<'input' | 'questions' | 'generating'>('input')
const aiAssistSendAnswers = ref<((answers: { id: string; answer: string }[]) => void) | null>(null)
const showRunHistory = ref(false)

const nodeTypes: any = { step: markRaw(StepNode), inputs: markRaw(InputsNode), memory: markRaw(MemoryNode) }
const edgeTypes: any = { pathfinding: markRaw(PathFindingEdge) }

const {
  onConnect, addEdges, fitView, getNodes, getEdges,
  applyNodeChanges, applyEdgeChanges, screenToFlowCoordinate
} = useVueFlow({
  defaultEdgeOptions: { type: 'pathfinding', animated: true },
})

onConnect((params: any) => {
  const sourceHandle = params.sourceHandle || ''


  if (sourceHandle.endsWith('_memory')) {
    const sourceStep = pipeline.value.steps.find(s => s.id === params.source)
    const targetMem = (pipeline.value.memories || []).find(m => m.id === params.target)
    if (!sourceStep || !targetMem) return

    const edgeId = `${params.source}_${params.target}_${sourceHandle}_${params.targetHandle || ''}`
    addEdges([{ ...params, id: edgeId }])
    syncEdgesToPipeline()
    return
  }


  const sourceStep = pipeline.value.steps.find(s => s.id === params.source)
  const targetStep = pipeline.value.steps.find(s => s.id === params.target)
  if (!sourceStep || !targetStep) return


  if (targetStep.tool?.type === ToolType.Start) return

  if (sourceStep.id === targetStep.id) return

  const edgeId = `${params.source}_${params.target}_${sourceHandle}_${params.targetHandle || ''}`
  addEdges([{ ...params, id: edgeId }])


  if (sourceStep.tool?.type === ToolType.If) {
    const handle = sourceHandle
    if (handle.includes('_true')) {
      sourceStep.next_steps_true.push(targetStep.id)
    } else if (handle.includes('_false')) {
      sourceStep.next_steps_false.push(targetStep.id)
    } else if (handle.includes('_after')) {
      sourceStep.next_steps.push(targetStep.id)
    }
  } else {
    sourceStep.next_steps.push(targetStep.id)
  }

  syncEdgesToPipeline()
})

function syncEdgesToPipeline() {
  const currentEdges = getEdges.value
  pipeline.value.edges = currentEdges.map(e => ({
    id: e.id,
    source: e.source,
    target: e.target,
    source_handle: e.sourceHandle || '',
    target_handle: e.targetHandle || '',
  }))
}



const flowNodes = computed<Node[]>(() => {
  const nodes: Node[] = []
  for (const step of pipeline.value.steps) {
    nodes.push({
      id: step.id,
      type: 'step',
      position: { x: step.pos_x || 250, y: step.pos_y || 200 },
      data: step,
    })
  }
  for (const mem of (pipeline.value.memories || [])) {
    nodes.push({
      id: mem.id,
      type: 'memory',
      position: { x: mem.pos_x || 250, y: mem.pos_y || 50 },
      data: mem,
    })
  }
  return nodes
})

const flowEdges = computed<Edge[]>(() => {
  return (pipeline.value.edges || []).map(e => {
    const isMemoryEdge = (e.source_handle || '').endsWith('_memory')
    if (isMemoryEdge) {
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.source_handle,
        targetHandle: e.target_handle,
        type: 'pathfinding',
        animated: false,
        interactionWidth: 20,
        selected: e.id === selectedEdge.value,
        style: e.id === selectedEdge.value
          ? { stroke: '#f87171', strokeWidth: 3 }
          : { stroke: '#38bdf8', strokeWidth: 2, strokeDasharray: '5 3' },
      }
    }
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.source_handle,
      targetHandle: e.target_handle,
      type: 'pathfinding',
      animated: true,
      interactionWidth: 20,
      selected: e.id === selectedEdge.value,
      style: e.id === selectedEdge.value ? { stroke: '#f87171', strokeWidth: 3 } : undefined,
    }
  })
})

onMounted(async () => {
  tools.value = await getTools()
  await loadModels()
  if (!route.query.new) {
    loading.value = true
    const data = await getPipeline(props.id)
    if (data && !('error' in data)) pipeline.value = data as AiPipeline
    loading.value = false

    try { pipelineRuns.value = await getPipelineRuns(props.id) } catch {}
  } else {
    pipeline.value.id = props.id
    const startStep = createPipelineStep()
    startStep.name = 'Start'
    startStep.is_start = true
    const startTool = createTool()
    Object.assign(startTool, getBaseToolDefaults(BASE_TOOL_ID.START))
    startStep.tool = startTool
    startStep.tool_id = BASE_TOOL_ID.START
    startStep.pos_x = 100
    startStep.pos_y = 250
    pipeline.value.steps.push(startStep)
  }
})

function onDragStart(event: DragEvent, type: string) {
  if (!event.dataTransfer) return
  event.dataTransfer.setData('application/vueflow', type)
  event.dataTransfer.effectAllowed = 'move'
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
}

function onDrop(event: DragEvent) {
  if (!event.dataTransfer) return
  const type = event.dataTransfer.getData('application/vueflow')
  if (!type) return

  const position = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })

  // Memory node drops
  if (type === 'mem_short' || type === 'mem_long') {
    const mem = createPipelineMemory(type === 'mem_long' ? 'long_term' : 'short_term')
    mem.pos_x = position.x
    mem.pos_y = position.y
    if (!pipeline.value.memories) pipeline.value.memories = []
    pipeline.value.memories.push(mem)
    return
  }

  const step = createPipelineStep()
  step.pos_x = position.x
  step.pos_y = position.y

  const defaults = getBaseToolDefaults(type)
  if (defaults) {
    const tool = createTool()
    Object.assign(tool, defaults)
    if (type === BASE_TOOL_ID.ASK_USER) tool.system_prompt = ASK_USER_SYSTEM_PROMPT
    step.tool = tool
    step.tool_id = type
    step.name = getBaseToolPrefix(type) + ' ' + step.id.substring(0, 4)
  } else {
    const savedTool = tools.value.find(t => t.id === type)
    if (savedTool) {
      step.tool = deepClone(savedTool)
      step.tool_id = savedTool.id
      step.name = savedTool.name
    }
  }

  pipeline.value.steps.push(step)
}

function selectStep(stepId: string) {

  const mem = (pipeline.value.memories || []).find(m => m.id === stepId)
  if (mem) {
    if (selectedMemory.value?.id === stepId) {
      selectedMemory.value = null
    } else {
      selectedMemory.value = mem
      selectedStep.value = null
    }
    return
  }

  if (selectedStep.value?.id === stepId) {
    selectedStep.value = null
  } else {
    selectedStep.value = pipeline.value.steps.find(s => s.id === stepId) || null
    if (selectedStep.value?.tool && !selectedStep.value.tool.response_structure) {
      selectedStep.value.tool.response_structure = []
    }
    selectedMemory.value = null
  }
}

function deleteStep() {
  if (!selectedStep.value) return
  const stepId = selectedStep.value.id
  pipeline.value.steps = pipeline.value.steps.filter(s => s.id !== stepId)
  pipeline.value.edges = pipeline.value.edges.filter(e => e.source !== stepId && e.target !== stepId)

  for (const s of pipeline.value.steps) {
    s.next_steps = s.next_steps.filter(id => id !== stepId)
    s.next_steps_true = s.next_steps_true.filter(id => id !== stepId)
    s.next_steps_false = s.next_steps_false.filter(id => id !== stepId)
  }
  selectedStep.value = null
}

function deleteMemory() {
  if (!selectedMemory.value) return
  const memId = selectedMemory.value.id
  pipeline.value.memories = (pipeline.value.memories || []).filter(m => m.id !== memId)
  pipeline.value.edges = pipeline.value.edges.filter(e => e.target !== memId)
  selectedMemory.value = null
}

function deleteEdge(edgeId: string) {
  const edge = pipeline.value.edges.find(e => e.id === edgeId)
  if (!edge) return
  pipeline.value.edges = pipeline.value.edges.filter(e => e.id !== edgeId)

  const sourceStep = pipeline.value.steps.find(s => s.id === edge.source)
  if (sourceStep) {
    const targetId = edge.target
    if (edge.source_handle.includes('_true')) {
      sourceStep.next_steps_true = sourceStep.next_steps_true.filter(id => id !== targetId)
    } else if (edge.source_handle.includes('_false')) {
      sourceStep.next_steps_false = sourceStep.next_steps_false.filter(id => id !== targetId)
    } else {
      sourceStep.next_steps = sourceStep.next_steps.filter(id => id !== targetId)
    }
  }
}

function selectTool(toolId: string) {
  if (!selectedStep.value) return
  selectedStep.value.tool_id = toolId

  const defaults = getBaseToolDefaults(toolId)
  if (defaults) {
    const tool = createTool()
    Object.assign(tool, defaults)
    if (toolId === BASE_TOOL_ID.ASK_USER) tool.system_prompt = ASK_USER_SYSTEM_PROMPT
    selectedStep.value.tool = tool
    if (toolId === BASE_TOOL_ID.LLM || toolId === BASE_TOOL_ID.ENDPOINT) {
      selectedStep.value.pre_process = `function process(input) {\n    return [input];\n}`
    }
  } else {
    const savedTool = tools.value.find(t => t.id === toolId)
    if (savedTool) {
      selectedStep.value.tool = deepClone(savedTool)
    }
  }

  loadStepKvFields()
}

function addStepInput() {
  if (!selectedStep.value?.tool) return
  if (!selectedStep.value.tool.request_inputs) selectedStep.value.tool.request_inputs = []
  selectedStep.value.tool.request_inputs.push({ name: '', value: '', type: PropertyType.TEXT, is_required: false, is_default: false })
}

function removeStepInput(idx: number) {
  if (!selectedStep.value?.tool?.request_inputs) return
  selectedStep.value.tool.request_inputs.splice(idx, 1)
}

const stepToolType = computed(() => selectedStep.value?.tool?.type ?? null)
function isType(t: ToolType) { return stepToolType.value === t }
const isStepLLM = computed(() => isType(ToolType.LLM))
const isStepEndpoint = computed(() => isType(ToolType.Endpoint))
const isStepAgent = computed(() => isType(ToolType.Agent))
const isStepIf = computed(() => isType(ToolType.If))
const isStepEnd = computed(() => isType(ToolType.End))
const isStepStart = computed(() => isType(ToolType.Start))
const isStepPipeline = computed(() => isType(ToolType.Pipeline))
const isStepLoopCounter = computed(() => isType(ToolType.LoopCounter))
const isStepWait = computed(() => isType(ToolType.Wait))
const isStepAskUser = computed(() => isType(ToolType.AskUser))
const isStepFileUpload = computed(() => isType(ToolType.FileUpload))
const isStepClaudeCode = computed(() => isType(ToolType.ClaudeCode))
const isStepParallel = computed(() => isType(ToolType.Parallel))

const showStepToolConfig = computed(() => {
  if (!selectedStep.value?.tool) return false
  const hidden = new Set([ToolType.End, ToolType.Start, ToolType.LoopCounter, ToolType.Wait, ToolType.FileUpload, ToolType.ClaudeCode])
  return !hidden.has(stepToolType.value!)
})

const showStepRetry = computed(() => {
  if (!selectedStep.value?.tool) return false
  const hidden = new Set([ToolType.End, ToolType.Start, ToolType.If, ToolType.LoopCounter, ToolType.Wait, ToolType.FileUpload, ToolType.ClaudeCode])
  return !hidden.has(stepToolType.value!)
})

const showStepValidation = computed(() => {
  if (!selectedStep.value?.tool) return false
  const hidden = new Set([ToolType.End, ToolType.Start, ToolType.If, ToolType.LoopCounter, ToolType.Wait, ToolType.FileUpload, ToolType.ClaudeCode, ToolType.Parallel])
  return !hidden.has(stepToolType.value!)
})

const stepEndpointHasBody = computed(() => {
  const m = selectedStep.value?.tool?.endpoint_method
  return m === EndpointMethod.POST || m === EndpointMethod.PUT
})


const stepEndpointHeaders = ref<{ key: string; value: string }[]>([])
const stepEndpointBody = ref<{ key: string; value: string }[]>([])
const stepEndpointQuery = ref<{ key: string; value: string }[]>([])


function loadStepKvFields() {
  const tool = selectedStep.value?.tool
  if (!tool) return
  stepEndpointHeaders.value = parseKv(tool.endpoint_headers)
  stepEndpointBody.value = parseKv(tool.endpoint_body)
  stepEndpointQuery.value = parseKv(tool.endpoint_query ?? '')
}

function syncStepKvToTool() {
  const tool = selectedStep.value?.tool
  if (!tool) return
  tool.endpoint_headers = serializeKv(stepEndpointHeaders.value)
  tool.endpoint_body = serializeKv(stepEndpointBody.value)
  tool.endpoint_query = serializeKv(stepEndpointQuery.value)
}

watch(stepEndpointHeaders, syncStepKvToTool, { deep: true })
watch(stepEndpointBody, syncStepKvToTool, { deep: true })
watch(stepEndpointQuery, syncStepKvToTool, { deep: true })


watch(() => selectedStep.value?.id, () => {
  if (selectedStep.value?.tool?.type === ToolType.Endpoint) {
    loadStepKvFields()
  }
})

function flattenResponseFields(prefix: string, fields: ResponseField[], vars: string[]) {
  for (const f of fields) {
    if (!f.key) continue
    const path = prefix + '.' + f.key
    vars.push(path)
    if (f.type === 'object' && f.children?.length) {
      flattenResponseFields(path, f.children, vars)
    }
  }
}

const pipelineTemplateVariables = computed(() => {
  const vars: string[] = []
  for (const inp of pipeline.value.inputs)
    if (inp.name) vars.push(inp.name)
  for (const step of pipeline.value.steps)
    if (step.id !== selectedStep.value?.id && step.name) {
      vars.push(step.name)
      if (step.tool?.type === ToolType.Agent) vars.push(step.name + 'Actions')
      // Add dot-path variables from response_structure
      const rs = step.tool?.response_structure
      if (rs?.length) flattenResponseFields(step.name, rs, vars)
    }
  if (selectedStep.value?.tool?.request_inputs)
    for (const inp of selectedStep.value.tool.request_inputs)
      if (inp.name && !vars.includes(inp.name)) vars.push(inp.name)
  return vars
})



const minimapNodeColors: Record<number, string> = {
  [ToolType.LLM]: 'rgba(168, 85, 247, 0.45)',
  [ToolType.Endpoint]: 'rgba(34, 197, 94, 0.45)',
  [ToolType.Pause]: 'rgba(234, 179, 8, 0.45)',
  [ToolType.Agent]: 'rgba(249, 115, 22, 0.45)',
  [ToolType.Pipeline]: 'rgba(59, 130, 246, 0.45)',
  [ToolType.If]: 'rgba(6, 182, 212, 0.45)',
  [ToolType.Parallel]: 'rgba(236, 72, 153, 0.45)',
  [ToolType.End]: 'rgba(239, 68, 68, 0.45)',
  [ToolType.Wait]: 'rgba(245, 158, 11, 0.45)',
  [ToolType.Start]: 'rgba(16, 185, 129, 0.45)',
  [ToolType.LoopCounter]: 'rgba(20, 184, 166, 0.45)',
  [ToolType.AskUser]: 'rgba(99, 102, 241, 0.45)',
  [ToolType.FileUpload]: 'rgba(56, 189, 248, 0.45)',
  [ToolType.ClaudeCode]: 'rgba(6, 182, 212, 0.45)',
}

function minimapNodeColor(node: any): string {
  const toolType = node.data?.tool?.type
  return minimapNodeColors[toolType] ?? '#6b7280'
}

function onNodeDragStop(event: any) {
  const node = event.node ?? event
  if (!node?.id) return
  const step = pipeline.value.steps.find(s => s.id === node.id)
  if (step) {
    step.pos_x = node.position.x
    step.pos_y = node.position.y
    return
  }
  const mem = (pipeline.value.memories || []).find(m => m.id === node.id)
  if (mem) {
    mem.pos_x = node.position.x
    mem.pos_y = node.position.y
  }
}

function syncPositions() {
  for (const node of getNodes.value) {
    if (node.type === 'step') {
      const step = pipeline.value.steps.find(s => s.id === node.id)
      if (step) {
        step.pos_x = node.position.x
        step.pos_y = node.position.y
      }
    } else if (node.type === 'memory') {
      const mem = (pipeline.value.memories || []).find(m => m.id === node.id)
      if (mem) {
        mem.pos_x = node.position.x
        mem.pos_y = node.position.y
      }
    }
  }
  syncEdgesToPipeline()
}

const saving = ref(false)

async function save() {
  if (saving.value) return
  saving.value = true
  syncPositions()
  try {
    await savePipeline(pipeline.value)
    toast('Pipeline saved', 'success')
  } catch (e: any) {
    toast(e.message || 'Failed to save pipeline', 'error')
  } finally {
    saving.value = false
  }
}

function openRunModal() {
  // Copy pipeline inputs so user can fill in values
  runInputs.value = pipeline.value.inputs.map(inp => ({ name: inp.name, value: inp.value || '', type: inp.type, data: inp.data }))
  showRunModal.value = true
}

async function confirmRun() {
  showRunModal.value = false
  syncPositions()
  // Apply user-entered values to pipeline inputs
  for (const ri of runInputs.value) {
    const inp = pipeline.value.inputs.find(i => i.name === ri.name)
    if (inp) inp.value = ri.value
  }
  await savePipeline(pipeline.value)
  const plRun = createPipelineRun(pipeline.value)
  const result = await apiRunPipeline(plRun)
  try { pipelineRuns.value = await getPipelineRuns(props.id) } catch {}
  router.push(`/pipeline-run/${result.id}`)
}

async function deleteRun(runId: string) {
  await deletePipelineRun(runId)
  pipelineRuns.value = pipelineRuns.value.filter(r => r.id !== runId)
}


function addPipelineInput() {
  pipeline.value.inputs.push({ name: '', value: '', type: PropertyType.TEXT, is_required: false, is_default: false })
}
function removePipelineInput(idx: number) {
  pipeline.value.inputs.splice(idx, 1)
}

// Long-term memory viewer
const showMemoryViewer = ref(false)
const memoryViewerMessages = ref<any[]>([])

async function viewLongTermMemory() {
  if (!selectedMemory.value) return
  try {
    const resp = await fetch(`/api/pipelines/${pipeline.value.id}/memories/${selectedMemory.value.id}`)
    const data = await resp.json()
    memoryViewerMessages.value = data.messages || []
    showMemoryViewer.value = true
  } catch {
    memoryViewerMessages.value = []
    showMemoryViewer.value = true
  }
}

async function clearLongTermMemory() {
  if (!selectedMemory.value) return
  try {
    await fetch(`/api/pipelines/${pipeline.value.id}/memories/${selectedMemory.value.id}`, { method: 'DELETE' })
    toast('Memory cleared', 'success')
  } catch {
    toast('Failed to clear memory', 'error')
  }
}

function onEdgeClick(event: any) {
  selectedEdge.value = event.edge?.id || null
  selectedStep.value = null
}

function deleteSelectedEdge() {
  if (!selectedEdge.value) return
  const edge = pipeline.value.edges.find(e => e.id === selectedEdge.value)
  if (edge) {
  
    const sourceStep = pipeline.value.steps.find(s => s.id === edge.source)
    if (sourceStep) {
      const targetId = edge.target
      if (edge.source_handle.includes('_true')) {
        sourceStep.next_steps_true = sourceStep.next_steps_true.filter(id => id !== targetId)
      } else if (edge.source_handle.includes('_false')) {
        sourceStep.next_steps_false = sourceStep.next_steps_false.filter(id => id !== targetId)
      } else {
        sourceStep.next_steps = sourceStep.next_steps.filter(id => id !== targetId)
      }
    }
    pipeline.value.edges = pipeline.value.edges.filter(e => e.id !== selectedEdge.value)
  }
  selectedEdge.value = null
}

function exportPipeline() {
  showExportModal.value = true
}

async function onExportConfirm(exportName: string, exportDescription: string, version: number) {
  if (!pipeline.value.export_uid) pipeline.value.export_uid = getUid()
  pipeline.value.export_version = version
  syncPositions()
  await savePipeline(pipeline.value)

  const data: any = deepClone(pipeline.value)
  delete data.id
  delete data.created_at
  delete data.updated_at
  // Convert image URL to base64 for portability
  if (data.image_url) {
    data.image_url = await imageUrlToBase64(data.image_url) || ''
  }
  data._export_type = 'pipeline'
  data._export_name = exportName
  data._export_description = exportDescription
  data._export_date = new Date().toISOString()

  // Collect unique real tools (skip base/structural tools with negative tool_id)
  const toolMap = new Map<string, AiTool>()
  for (const step of pipeline.value.steps) {
    if (!step.tool_id || step.tool_id.startsWith('-')) continue
    const tool = step.tool ?? tools.value.find(t => t.id === step.tool_id)
    if (tool?.id) toolMap.set(tool.id, tool)
  }
  // Assign export_uid to tools that don't have one yet, and persist on the ORIGINAL tool only
  for (const tool of toolMap.values()) {
    if (!tool.export_uid) {
      const uid = getUid()
      tool.export_uid = uid
      // Save export_uid on the original tool, NOT the step copy (which may have pipeline-specific overrides)
      const originalTool = tools.value.find(t => t.id === tool.id)
      if (originalTool) {
        originalTool.export_uid = uid
        await saveTool(originalTool)
      }
    }
  }
  const embeddedTools = await Promise.all([...toolMap.values()].map(async t => {
    const clone = deepClone(t)
    delete clone.created_at
    delete clone.updated_at
    if (clone.image_url) {
      clone.image_url = await imageUrlToBase64(clone.image_url) || ''
    }
    return clone
  }))
  data._tools = embeddedTools

  // Aggregate pip packages from all embedded tools
  const pkgSet = new Set<string>()
  for (const t of embeddedTools) {
    for (const pkg of (t.pip_dependencies || [])) pkgSet.add(pkg)
  }
  data._pip_packages = [...pkgSet]

  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${exportName || 'pipeline'}.json`
  a.click()
  URL.revokeObjectURL(url)
}

async function removePipeline() {
  if (!confirm('Are you sure you want to delete this pipeline?')) return
  await apiDeletePipeline(pipeline.value.id)
  router.push('/pipelines')
}

// Handle keyboard delete
function onKeyDown(e: KeyboardEvent) {
  if (e.key === 'Delete' || e.key === 'Backspace') {
    // Only delete if not typing in an input
    const tag = (e.target as HTMLElement).tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
    if (selectedEdge.value) {
      deleteSelectedEdge()
    } else if (selectedMemory.value) {
      deleteMemory()
    } else if (selectedStep.value) {
      deleteStep()
    }
  }
}



function openAiAssist() {
  aiAssistStatus.value = ''
  aiAssistStreamJson.value = ''
  aiAssistResult.value = null
  aiAssistUsage.value = null
  aiAssistQuestions.value = []
  aiAssistAnswers.value = {}
  aiAssistPhase.value = 'input'
  aiAssistSendAnswers.value = null
  showAiAssist.value = true
}

function closeAiAssist() {
  if (aiAssistAbort.value) aiAssistAbort.value()
  aiAssistLoading.value = false
  showAiAssist.value = false
}

function handleAiAssistEvent(event: PipelineAiAssistEvent) {
  if (event.type === 'status') {
    aiAssistStatus.value = event.text || ''
  } else if (event.type === 'questions') {
    aiAssistQuestions.value = event.questions || []
    aiAssistAnswers.value = {}
    for (const q of aiAssistQuestions.value) {
      aiAssistAnswers.value[q.id] = q.type === 'choice' && q.options?.length ? q.options[0] : ''
    }
    aiAssistPhase.value = 'questions'
    aiAssistLoading.value = false
    aiAssistStatus.value = ''
  } else if (event.type === 'delta') {
    aiAssistStreamJson.value += event.text || ''
  } else if (event.type === 'result') {
    aiAssistResult.value = event.pipeline_config || null
    if (event.usage) {
      const u = event.usage
      const m = models.value.find((m: any) => m.id === u.model)
      const inCost = m ? ((u.input_tokens || 0) / 1_000_000) * m.input_cost : 0
      const outCost = m ? ((u.output_tokens || 0) / 1_000_000) * m.output_cost : 0
      aiAssistUsage.value = { input_tokens: u.input_tokens || 0, output_tokens: u.output_tokens || 0, cost: inCost + outCost }
    }
    aiAssistStatus.value = 'Done'
    aiAssistLoading.value = false
    aiAssistPhase.value = 'generating'
  } else if (event.type === 'error') {
    aiAssistStatus.value = ''
    aiAssistLoading.value = false
    toast(event.text || 'AI assist failed', 'error')
  }
}

async function generatePipelineWithAi(phase: 'clarify' | 'generate' = 'clarify') {
  if (aiAssistLoading.value || !aiAssistDescription.value.trim()) return
  aiAssistLoading.value = true
  aiAssistStatus.value = 'Connecting...'
  aiAssistStreamJson.value = ''
  aiAssistResult.value = null
  aiAssistPhase.value = 'generating'

  const { promise, abort, sendAnswers } = wsAiAssistPipeline(
    aiAssistDescription.value,
    aiAssistModel.value,
    pipeline.value,
    handleAiAssistEvent,
    phase,
  )
  aiAssistAbort.value = abort
  aiAssistSendAnswers.value = sendAnswers

  try {
    await promise
  } catch {
    if (aiAssistLoading.value) {
      aiAssistStatus.value = ''
      aiAssistLoading.value = false
      toast('AI assist connection failed', 'error')
    }
  }
}

function submitClarificationAnswers() {
  if (!aiAssistSendAnswers.value) return
  const answers = aiAssistQuestions.value.map(q => ({
    id: q.id,
    answer: aiAssistAnswers.value[q.id] || '',
  }))
  aiAssistSendAnswers.value(answers)
  aiAssistLoading.value = true
  aiAssistStatus.value = 'Building pipeline with your answers...'
  aiAssistPhase.value = 'generating'
}

function applyAiPipelineResult() {
  if (!aiAssistResult.value) return
  const config = aiAssistResult.value

  // Update pipeline metadata
  if (config.name) pipeline.value.name = config.name
  if (config.description) pipeline.value.description = config.description
  if (config.tag) pipeline.value.tag = config.tag
  if (config.guidance) pipeline.value.guidance = config.guidance

  // Update pipeline inputs
  if (Array.isArray(config.inputs) && config.inputs.length) {
    pipeline.value.inputs = config.inputs.map((inp: any, idx: number) => ({
      name: inp.name || '',
      value: '',
      type: inp.type ?? PropertyType.TEXT,
      is_required: inp.is_required ?? false,
      is_default: inp.is_default ?? (idx === 0),
      data: null,
    }))
  }

  // Find the existing Start step
  const startStep = pipeline.value.steps.find(s => s.tool?.type === ToolType.Start)
  const startId = startStep?.id || ''

  // Build new steps from AI output
  const aiSteps = config.steps || []
  const newSteps: AiPipelineStep[] = startStep ? [startStep] : []

  // Map AI step IDs to real step IDs
  const idMap: Record<string, string> = { '__START__': startId }

  for (const aiStep of aiSteps) {
    const step = createPipelineStep()
    idMap[aiStep.id] = step.id

    step.name = aiStep.name || 'Step'
    step.pos_x = aiStep.pos_x ?? 400
    step.pos_y = aiStep.pos_y ?? 250
    step.next_steps = []
    step.next_steps_true = []
    step.next_steps_false = []

    // Build the embedded tool with CORRECT type
    const toolType = aiStep.tool_type
    const tool = createTool()

    // Set tool type explicitly — this is the critical part
    const typeMap: Record<number, { type: ToolType; defaultId: string }> = {
      0:  { type: ToolType.LLM,          defaultId: '-1' },
      1:  { type: ToolType.Endpoint,     defaultId: '-2' },
      3:  { type: ToolType.Agent,        defaultId: '-10' },
      5:  { type: ToolType.If,           defaultId: '-3' },
      7:  { type: ToolType.End,          defaultId: '-5' },
      8:  { type: ToolType.Wait,         defaultId: '-6' },
      10: { type: ToolType.LoopCounter,  defaultId: '-4' },
      11: { type: ToolType.AskUser,      defaultId: '-7' },
      12: { type: ToolType.FileUpload,   defaultId: '-8' },
      15: { type: ToolType.ClaudeCode,  defaultId: '-11' },
    }
    const mapped = typeMap[toolType] || { type: ToolType.LLM, defaultId: '-1' }
    tool.type = mapped.type
    tool.name = aiStep.name || 'Step'
    step.tool_id = aiStep.tool_id || mapped.defaultId

    // If tool_id references a saved tool, use the saved tool's deep copy instead
    const savedToolId = step.tool_id
    if (savedToolId && !savedToolId.startsWith('-')) {
      const savedTool = tools.value.find(t => t.id === savedToolId)
      if (savedTool) {
        step.tool = deepClone(savedTool)
        // Still apply AI-provided prompt overrides
        if (aiStep.prompt) step.tool!.prompt = aiStep.prompt
        if (aiStep.system_prompt) step.tool!.system_prompt = aiStep.system_prompt
        newSteps.push(step)
        continue
      }
    }

    // Apply AI-provided fields to the tool
    if (aiStep.prompt !== undefined) tool.prompt = aiStep.prompt
    if (aiStep.system_prompt !== undefined) tool.system_prompt = aiStep.system_prompt
    if (aiStep.model !== undefined) tool.model = aiStep.model

    // Endpoint fields
    if (aiStep.endpoint_url !== undefined) tool.endpoint_url = aiStep.endpoint_url
    if (aiStep.endpoint_method !== undefined) tool.endpoint_method = aiStep.endpoint_method
    if (aiStep.endpoint_headers !== undefined) tool.endpoint_headers = aiStep.endpoint_headers
    if (aiStep.endpoint_body !== undefined) tool.endpoint_body = aiStep.endpoint_body
    if (aiStep.endpoint_query !== undefined) tool.endpoint_query = aiStep.endpoint_query

    // Request inputs for the step's tool
    if (Array.isArray(aiStep.request_inputs) && aiStep.request_inputs.length) {
      tool.request_inputs = aiStep.request_inputs.map((inp: any, idx: number) => ({
        name: inp.name || '',
        value: '',
        description: inp.description || '',
        type: inp.type ?? PropertyType.TEXT,
        is_required: inp.is_required ?? true,
        locked: true,
        index: idx,
        is_default: inp.is_default ?? (idx === 0),
        data: null,
      }))
    }

    // Agent functions
    if (Array.isArray(aiStep.agent_functions) && aiStep.agent_functions.length) {
      tool.agent_functions = aiStep.agent_functions.map((fn: any) => ({
        uid: getUid(6),
        name: fn.name || '',
        description: fn.description || '',
        is_enabled: true,
        is_deleted: false,
        function_string: fn.function_string || '',
      }))
    }

    // Pip dependencies
    if (Array.isArray(aiStep.pip_dependencies)) {
      tool.pip_dependencies = aiStep.pip_dependencies
    }

    // Response structure
    if (Array.isArray(aiStep.response_structure)) {
      tool.response_structure = aiStep.response_structure
    }

    // LoopCounter max_passes
    if (aiStep.max_passes !== undefined) {
      (step as any).max_passes = aiStep.max_passes
    }

    step.tool = tool
    newSteps.push(step)
  }

  // Now resolve next_steps references using the idMap
  for (const aiStep of aiSteps) {
    const realId = idMap[aiStep.id]
    const step = newSteps.find(s => s.id === realId)
    if (!step) continue

    if (Array.isArray(aiStep.next_steps)) {
      step.next_steps = aiStep.next_steps.map((id: string) => idMap[id] || id).filter(Boolean)
    }
    if (Array.isArray(aiStep.next_steps_true)) {
      step.next_steps_true = aiStep.next_steps_true.map((id: string) => idMap[id] || id).filter(Boolean)
    }
    if (Array.isArray(aiStep.next_steps_false)) {
      step.next_steps_false = aiStep.next_steps_false.map((id: string) => idMap[id] || id).filter(Boolean)
    }
  }

  // Also resolve Start step next_steps from edges that come from __START__
  if (startStep) {
    startStep.next_steps = []
  }

  // Build edges from AI output
  const newEdges: Array<{ id: string; source: string; target: string; source_handle: string; target_handle: string }> = []
  for (const aiEdge of (config.edges || [])) {
    const source = idMap[aiEdge.source] || aiEdge.source
    const target = idMap[aiEdge.target] || aiEdge.target
    if (!source || !target) continue
    const srcSuffix = aiEdge.source_handle || '_source'
    const tgtSuffix = aiEdge.target_handle || '_target'
    newEdges.push({
      id: getUid(),
      source,
      target,
      source_handle: `${source}${srcSuffix}`,
      target_handle: `${target}${tgtSuffix}`,
    })
    // Also populate start step's next_steps
    if (aiEdge.source === '__START__' && startStep) {
      const realTarget = idMap[aiEdge.target] || aiEdge.target
      if (realTarget && !startStep.next_steps.includes(realTarget)) {
        startStep.next_steps.push(realTarget)
      }
    }
  }

  pipeline.value.steps = newSteps
  pipeline.value.edges = newEdges

  toast('AI pipeline configuration applied', 'success')
  showAiAssist.value = false

  // Fit view after a tick to let Vue Flow update
  nextTick(() => { setTimeout(() => fitView(), 100) })
}
</script>

<template>
  <div class="flex h-full" @keydown="onKeyDown" tabindex="0">
    <!-- Left: Palette & pipeline settings -->
    <div class="w-72 bg-gray-900 border-r border-gray-800 flex flex-col">
      <!-- Header -->
      <div class="p-4 border-b border-gray-800">
        <div class="flex items-center gap-3">
          <button @click="router.push('/pipelines')" class="text-gray-400 hover:text-gray-50 text-sm">&larr;</button>
          <h1 class="text-lg font-bold truncate">{{ route.query.new ? 'New Pipeline' : pipeline.name || 'Edit Pipeline' }}</h1>
        </div>
      </div>

      <!-- AI Assist button -->
      <div class="px-4 py-2 border-b border-gray-800">
        <button
          @click="openAiAssist"
          class="w-full flex items-center justify-center gap-2 px-3 py-2 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 rounded-lg text-sm font-medium text-purple-400 transition-colors"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
          AI Assist
        </button>
      </div>

      <!-- Scrollable content -->
      <div class="flex-1 overflow-y-auto min-h-0">

      <!-- Settings -->
      <div class="p-4 border-b border-gray-800 space-y-3">
        <div class="text-xs text-gray-500 uppercase font-medium">Settings</div>
        <div>
          <label class="block text-xs text-gray-400 mb-1">Name</label>
          <input v-model="pipeline.name" placeholder="Name" class="input-sm" />
        </div>
        <div>
          <label class="block text-xs text-gray-400 mb-1">Description</label>
          <textarea v-model="pipeline.description" placeholder="Description" rows="2" class="input-sm resize-y"></textarea>
        </div>
        <div>
          <label class="block text-xs text-gray-400 mb-1">Tag</label>
          <input v-model="pipeline.tag" placeholder="Tag" class="input-sm" />
        </div>

        <!-- Validation Model -->
        <div>
          <label class="block text-xs text-gray-400 mb-1">Validation Model</label>
          <p class="text-[10px] text-gray-600 mb-1">Default model for step output validation</p>
          <ModelSelectDropdown v-model="pipeline.validation_model" :models="models" />
        </div>

        <!-- Pipeline Image -->
        <div>
          <label class="block text-xs text-gray-400 mb-1">Image</label>
          <div class="flex items-center gap-3">
            <div v-if="pipeline.image_url" class="relative group">
              <img :src="pipeline.image_url" class="w-16 h-16 rounded-lg object-cover border border-gray-700 bg-black" />
              <button @click="removeImage" class="absolute -top-1.5 -right-1.5 w-5 h-5 bg-red-600 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity" title="Remove image">x</button>
            </div>
            <LetterAvatar v-else :letter="pipeline.name" :size="64" />
            <button @click="imageFileInput?.click()" :disabled="uploadingImage" class="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs text-gray-300 transition-colors disabled:opacity-50">
              {{ uploadingImage ? 'Uploading...' : 'Upload' }}
            </button>
            <input ref="imageFileInput" type="file" accept="image/*" class="hidden" @change="onImageSelected" />
          </div>
        </div>
      </div>

      <!-- Pipeline Inputs -->
      <div class="p-4 border-b border-gray-800">
        <div class="flex items-center justify-between mb-2">
          <div class="text-xs text-gray-500 uppercase font-medium">Inputs</div>
          <button @click="addPipelineInput" class="text-xs text-blue-400 hover:text-blue-300">+ Add</button>
        </div>
        <div class="space-y-2">
          <div v-for="(inp, idx) in pipeline.inputs" :key="idx" class="space-y-1 p-2 bg-gray-800/50 rounded border border-gray-800">
            <div class="flex items-center gap-1">
              <input v-model="inp.name" placeholder="Name" class="flex-1 px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" />
              <button @click="configInput = inp; showInputConfig = true" type="button" title="Configure input" class="shrink-0 p-1 text-gray-500 hover:text-gray-300 transition-colors">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z" /><circle cx="12" cy="12" r="3" /></svg>
              </button>
              <button @click="removePipelineInput(idx)" class="text-red-400 hover:text-red-300 text-xs">x</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Step palette -->
      <div class="p-4 flex-1">
        <div class="text-xs text-gray-500 uppercase font-medium mb-2">Steps</div>
        <div class="space-y-1">
          <div
            draggable="true" @dragstart="onDragStart($event, '-3')"
            class="flex items-center gap-2 px-2 py-1.5 text-sm text-cyan-300 bg-cyan-500/10 border border-cyan-500/30 rounded cursor-grab hover:bg-cyan-500/20 transition-colors"
          >
            <span class="w-2 h-2 rounded-full bg-cyan-400"></span> If
          </div>
          <div
            draggable="true" @dragstart="onDragStart($event, '-4')"
            class="flex items-center gap-2 px-2 py-1.5 text-sm text-teal-300 bg-teal-500/10 border border-teal-500/30 rounded cursor-grab hover:bg-teal-500/20 transition-colors"
          >
            <span class="w-2 h-2 rounded-full bg-teal-400"></span> Loop Counter
          </div>
          <div
            draggable="true" @dragstart="onDragStart($event, '-6')"
            class="flex items-center gap-2 px-2 py-1.5 text-sm text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded cursor-grab hover:bg-amber-500/20 transition-colors"
          >
            <span class="w-2 h-2 rounded-full bg-amber-400"></span> Wait
          </div>
          <div
            draggable="true" @dragstart="onDragStart($event, '-5')"
            class="flex items-center gap-2 px-2 py-1.5 text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded cursor-grab hover:bg-red-500/20 transition-colors"
          >
            <span class="w-2 h-2 rounded-full bg-red-400"></span> End
          </div>
          <div
            draggable="true" @dragstart="onDragStart($event, '-7')"
            class="flex items-center gap-2 px-2 py-1.5 text-sm text-indigo-300 bg-indigo-500/10 border border-indigo-500/30 rounded cursor-grab hover:bg-indigo-500/20 transition-colors"
          >
            <span class="w-2 h-2 rounded-full bg-indigo-400"></span> Ask User
          </div>
          <div
            draggable="true" @dragstart="onDragStart($event, '-8')"
            class="flex items-center gap-2 px-2 py-1.5 text-sm text-sky-300 bg-sky-500/10 border border-sky-500/30 rounded cursor-grab hover:bg-sky-500/20 transition-colors"
          >
            <span class="w-2 h-2 rounded-full bg-sky-400"></span> File Upload
          </div>
          <div
            draggable="true" @dragstart="onDragStart($event, '-11')"
            class="flex items-center gap-2 px-2 py-1.5 text-sm text-cyan-300 bg-cyan-500/10 border border-cyan-500/30 rounded cursor-grab hover:bg-cyan-500/20 transition-colors"
          >
            <span class="w-2 h-2 rounded-full bg-cyan-400"></span> Claude Code
          </div>
          <div
            draggable="true" @dragstart="onDragStart($event, '-1')"
            class="flex items-center gap-2 px-2 py-1.5 text-sm text-purple-300 bg-purple-500/10 border border-purple-500/30 rounded cursor-grab hover:bg-purple-500/20 transition-colors"
          >
            <span class="w-2 h-2 rounded-full bg-purple-400"></span> Base LLM
          </div>
          <div
            draggable="true" @dragstart="onDragStart($event, '-2')"
            class="flex items-center gap-2 px-2 py-1.5 text-sm text-green-300 bg-green-500/10 border border-green-500/30 rounded cursor-grab hover:bg-green-500/20 transition-colors"
          >
            <span class="w-2 h-2 rounded-full bg-green-400"></span> Base Endpoint
          </div>
          <div
            draggable="true" @dragstart="onDragStart($event, '-10')"
            class="flex items-center gap-2 px-2 py-1.5 text-sm text-blue-300 bg-blue-500/10 border border-blue-500/30 rounded cursor-grab hover:bg-blue-500/20 transition-colors"
          >
            <span class="w-2 h-2 rounded-full bg-blue-400"></span> AI Tool
          </div>
        </div>

        <div class="text-xs text-gray-500 uppercase font-medium mt-4 mb-2">Memory</div>
        <div class="space-y-1">
          <div
            draggable="true" @dragstart="onDragStart($event, 'mem_short')"
            class="flex items-center gap-2 px-2 py-1.5 text-sm text-sky-300 bg-sky-500/10 border border-sky-500/30 border-dashed rounded cursor-grab hover:bg-sky-500/20 transition-colors"
          >
            <span class="w-2 h-2 rounded-full bg-sky-400"></span> Short Term Memory
          </div>
          <div
            draggable="true" @dragstart="onDragStart($event, 'mem_long')"
            class="flex items-center gap-2 px-2 py-1.5 text-sm text-amber-300 bg-amber-500/10 border border-amber-500/30 border-dashed rounded cursor-grab hover:bg-amber-500/20 transition-colors"
          >
            <span class="w-2 h-2 rounded-full bg-amber-400"></span> Long Term Memory
          </div>
        </div>
      </div>

      <!-- Recent Runs -->
      <div class="p-4 border-t border-gray-800">
        <button @click="showRunHistory = !showRunHistory" class="flex items-center justify-between w-full text-xs text-gray-500 uppercase font-medium mb-2">
          <span>Recent Runs ({{ pipelineRuns.length }})</span>
          <span class="text-gray-600">{{ showRunHistory ? '&#9650;' : '&#9660;' }}</span>
        </button>
        <div v-if="showRunHistory" class="space-y-1 max-h-48 overflow-auto">
          <div v-if="pipelineRuns.length === 0" class="text-xs text-gray-600">No runs yet</div>
          <div
            v-for="r in pipelineRuns.slice(0, 10)" :key="r.id"
            class="flex items-center gap-2 px-2 py-1.5 rounded text-xs cursor-pointer hover:bg-gray-800 transition-colors group"
            @click="router.push(`/pipeline-run/${r.id}`)"
          >
            <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="{
              'bg-gray-400': r.status === PipelineStatusType.Pending,
              'bg-blue-400': r.status === PipelineStatusType.Running,
              'bg-green-400': r.status === PipelineStatusType.Completed,
              'bg-red-400': r.status === PipelineStatusType.Failed,
              'bg-yellow-400': r.status === PipelineStatusType.Paused,
            }"></span>
            <span class="truncate flex-1" :class="{
              'text-gray-400': r.status === PipelineStatusType.Pending,
              'text-blue-400': r.status === PipelineStatusType.Running,
              'text-green-400': r.status === PipelineStatusType.Completed,
              'text-red-400': r.status === PipelineStatusType.Failed,
              'text-yellow-400': r.status === PipelineStatusType.Paused,
            }">{{ r.created_at ? new Date(r.created_at).toLocaleString() : r.id }}</span>
            <button
              @click.stop="deleteRun(r.id)"
              class="text-red-400/0 group-hover:text-red-400 hover:!text-red-300 shrink-0"
            >&times;</button>
          </div>
        </div>
      </div>

      </div><!-- /scrollable -->

      <!-- Actions -->
      <div class="p-3 border-t border-gray-800 space-y-2">
        <button v-if="auth.canEdit('pipelines')" @click="save" :disabled="saving" class="w-full px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors">
          {{ saving ? 'Saving...' : 'Save' }}
        </button>
        <button @click="openRunModal" class="w-full px-3 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium transition-colors">
          Run
        </button>
        <div class="flex gap-2">
          <button @click="exportPipeline" class="flex-1 px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition-colors">
            Export
          </button>
          <button v-if="auth.canDelete('pipelines')" @click="removePipeline" class="flex-1 px-3 py-2 bg-red-900/40 hover:bg-red-900/60 text-red-400 rounded-lg text-sm font-medium transition-colors">
            Delete
          </button>
        </div>
      </div>
    </div>

    <!-- Flow canvas -->
    <div class="flex-1 relative" @dragover="onDragOver" @drop="onDrop($event)">
      <VueFlow
        :nodes="flowNodes"
        :edges="flowEdges"
        :node-types="nodeTypes"
        :edge-types="edgeTypes"
        @node-click="({ node }: any) => { selectStep(node.id); selectedEdge = null; }"
        @node-drag-stop="onNodeDragStop"
        @edge-click="onEdgeClick"
        @pane-click="() => { selectedEdge = null; selectedMemory = null }"
        @nodes-change="applyNodeChanges"
        @edges-change="(changes: any) => { applyEdgeChanges(changes); syncEdgesToPipeline() }"
        class="bg-gray-950"
        :default-viewport="{ x: 0, y: 0, zoom: 0.8 }"
      >
        <Background />
        <Controls />
        <MiniMap mask-color="rgba(0, 0, 0, 0.7)" :node-color="minimapNodeColor" node-stroke-color="transparent" />
      </VueFlow>
    </div>

    <!-- Right: Memory properties panel -->
    <div v-if="selectedMemory" class="w-80 bg-gray-900 border-l border-gray-800 overflow-auto flex flex-col">
      <div class="p-4 border-b border-gray-800 flex items-center justify-between">
        <h3 class="font-semibold text-gray-50 text-sm">Memory Properties</h3>
        <button @click="selectedMemory = null" class="text-gray-400 hover:text-gray-50">x</button>
      </div>
      <div class="p-4 space-y-4 flex-1 overflow-auto">
        <div>
          <label class="block text-xs text-gray-400 mb-1">Name</label>
          <input v-model="selectedMemory.name" class="input-sm" />
        </div>
        <div>
          <label class="block text-xs text-gray-400 mb-1">Type</label>
          <div class="text-sm px-2 py-1.5 rounded" :class="selectedMemory.type === 'long_term' ? 'bg-amber-900/30 text-amber-300' : 'bg-sky-900/30 text-sky-300'">
            {{ selectedMemory.type === 'long_term' ? 'Long Term' : 'Short Term' }}
          </div>
        </div>
        <div>
          <label class="block text-xs text-gray-400 mb-1">Max Messages (0 = unlimited)</label>
          <input type="number" v-model.number="selectedMemory.max_messages" min="0" class="input-sm" />
        </div>
        <div v-if="selectedMemory.type === 'short_term'" class="text-xs text-sky-400 p-2 bg-sky-500/10 rounded border border-sky-500/20">
          Accumulates conversation history during a single run. Connected steps get this history injected and contribute their exchanges.
        </div>
        <div v-else class="text-xs text-amber-400 p-2 bg-amber-500/10 rounded border border-amber-500/20">
          Persists conversation history between runs. Useful for pipelines that run repeatedly and should remember prior interactions.
        </div>
        <div v-if="selectedMemory.type === 'long_term'" class="space-y-2">
          <button @click="viewLongTermMemory" class="w-full px-3 py-1.5 bg-amber-900/30 text-amber-300 rounded text-sm hover:bg-amber-900/50 transition-colors">
            View Memory
          </button>
          <button @click="clearLongTermMemory" class="w-full px-3 py-1.5 bg-red-900/30 text-red-400 rounded text-sm hover:bg-red-900/50 transition-colors">
            Clear Memory
          </button>
        </div>
        <button @click="deleteMemory" class="w-full px-3 py-1.5 bg-red-900/30 text-red-400 rounded text-sm hover:bg-red-900/50 transition-colors mt-4">
          Delete Memory Node
        </button>
      </div>
      <!-- Long term memory viewer modal -->
      <Teleport to="body">
        <div v-if="showMemoryViewer" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" @click.self="showMemoryViewer = false">
          <div class="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-lg p-6 space-y-4 max-h-[80vh] overflow-auto">
            <div class="flex items-center justify-between">
              <h2 class="text-lg font-bold text-gray-50">Long Term Memory</h2>
              <button @click="showMemoryViewer = false" class="text-gray-400 hover:text-gray-50">x</button>
            </div>
            <div v-if="!memoryViewerMessages.length" class="text-sm text-gray-500">No messages stored yet.</div>
            <div v-for="(msg, mi) in memoryViewerMessages" :key="mi" class="rounded p-2 text-sm" :class="msg.role === 'user' ? 'bg-blue-900/20 text-blue-200' : 'bg-gray-800 text-gray-300'">
              <div class="text-[10px] text-gray-500 mb-1">{{ msg.role }} &middot; {{ msg.step_name }} &middot; {{ msg.timestamp }}</div>
              <div class="whitespace-pre-wrap">{{ msg.content?.substring(0, 500) }}</div>
            </div>
          </div>
        </div>
      </Teleport>
    </div>

    <!-- Right: Step properties panel -->
    <div v-if="selectedStep && !selectedMemory" class="w-80 bg-gray-900 border-l border-gray-800 overflow-auto flex flex-col">
      <div class="p-4 border-b border-gray-800 flex items-center justify-between">
        <h3 class="font-semibold text-gray-50 text-sm">Step Properties</h3>
        <button @click="selectedStep = null" class="text-gray-400 hover:text-gray-50">x</button>
      </div>

      <div class="p-4 space-y-4 flex-1 overflow-auto">
        <!-- Step name -->
        <div>
          <label class="block text-xs text-gray-400 mb-1">Name</label>
          <input v-model="selectedStep.name" class="input-sm" />
        </div>

        <!-- Tool selection (not for Start steps) -->
        <div v-if="!isStepStart">
          <label class="block text-xs text-gray-400 mb-1">Tool Type</label>
          <div v-if="selectedStep.tool?.image_url" class="flex items-center gap-2 mb-2">
            <img :src="selectedStep.tool.image_url" class="w-10 h-10 rounded-lg object-cover border border-gray-700 bg-black" />
            <span class="text-sm text-gray-300 truncate">{{ selectedStep.tool.name }}</span>
          </div>
          <ToolSelectDropdown
            :model-value="selectedStep.tool_id"
            @update:model-value="selectTool($event)"
            :tools="tools"
          />
        </div>

        <!-- Flags -->
        <div class="flex gap-3 flex-wrap" v-if="!isStepStart && !isStepEnd">
          <label class="flex items-center gap-1 text-xs text-gray-400">
            <input type="checkbox" v-model="selectedStep.disabled" /> Disabled
          </label>
          <label class="flex items-center gap-1 text-xs text-gray-400">
            <input type="checkbox" v-model="selectedStep.pause_after" /> Pause After
          </label>
        </div>

        <!-- End step message -->
        <div v-if="isStepEnd" class="text-xs text-red-400 p-2 bg-red-500/10 rounded border border-red-500/20">
          This step stops pipeline execution at this point.
        </div>

        <!-- Start step message -->
        <div v-if="isStepStart" class="text-xs text-emerald-400 p-2 bg-emerald-500/10 rounded border border-emerald-500/20">
          Pipeline entry point. Connect to the first step.
        </div>

        <!-- If step info -->
        <div v-if="isStepIf" class="text-xs text-cyan-400 p-2 bg-cyan-500/10 rounded border border-cyan-500/20">
          AI evaluates the prompt and returns <code class="bg-gray-800 px-1 rounded">true</code> / <code class="bg-gray-800 px-1 rounded">false</code> with reasoning.
          Connect the green handle (True), red handle (False), and gray handle (After).
        </div>

        <!-- Loop Counter step info -->
        <div v-if="isStepLoopCounter" class="text-xs text-teal-400 p-2 bg-teal-500/10 rounded border border-teal-500/20">
          Counts loop passes. Halts the branch after max passes is reached.
        </div>

        <!-- Ask User step info -->
        <div v-if="isStepAskUser" class="text-xs text-indigo-400 p-2 bg-indigo-500/10 rounded border border-indigo-500/20">
          LLM reviews the input and decides if clarification is needed. If so, it presents questions to the user during the run. Answers are fed back to the LLM until it's satisfied, then outputs a summary.
        </div>

        <!-- Wait step info -->
        <div v-if="isStepWait" class="text-xs text-amber-400 p-2 bg-amber-500/10 rounded border border-amber-500/20">
          Waits for all incoming branches to complete before continuing. Branches not connected to this step are unaffected.
        </div>

        <!-- File Upload step info + settings -->
        <div v-if="isStepFileUpload" class="text-xs text-sky-400 p-2 bg-sky-500/10 rounded border border-sky-500/20">
          Pauses the pipeline and shows a file upload UI. After files are uploaded, the pipeline resumes with file paths as JSON array output.
        </div>
        <div v-if="isStepFileUpload && selectedStep.tool" class="space-y-3">
          <div>
            <label class="block text-xs text-gray-400 mb-1">Upload Message</label>
            <TemplateInput v-model="selectedStep.tool.prompt" :variables="pipelineTemplateVariables" mode="textarea" :rows="2" placeholder="Upload your data files" inputClass="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" />
          </div>
        </div>

        <!-- Claude Code step info + settings -->
        <div v-if="isStepClaudeCode" class="text-xs text-cyan-400 p-2 bg-cyan-500/10 rounded border border-cyan-500/20">
          Runs Claude Code CLI in headless mode. Provide a prompt describing what to accomplish — Claude Code will use its tools (Read, Edit, Bash, etc.) to complete the task.
        </div>
        <div v-if="isStepClaudeCode && selectedStep.tool" class="space-y-3">
          <div>
            <label class="block text-xs text-gray-400 mb-1">Prompt</label>
            <TemplateInput v-model="selectedStep.tool.prompt" :variables="pipelineTemplateVariables" mode="textarea" :rows="4" placeholder="Describe what Claude Code should do..." inputClass="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500" />
          </div>
          <div>
            <label class="block text-xs text-gray-400 mb-1">System Prompt (optional)</label>
            <TemplateInput v-model="selectedStep.tool.system_prompt" :variables="pipelineTemplateVariables" mode="textarea" :rows="2" placeholder="Additional instructions..." inputClass="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500" />
          </div>
        </div>

        <!-- Loop Counter settings -->
        <div v-if="isStepLoopCounter && selectedStep.tool" class="space-y-3">
          <div>
            <label class="block text-xs text-gray-400 mb-1">Max Passes</label>
            <input type="number" v-model.number="selectedStep.tool.max_passes" min="1" class="input-sm" />
          </div>
        </div>

        <!-- Tabs for tool-specific properties -->
        <div v-if="selectedStep.tool && showStepToolConfig" class="space-y-4">
          <div class="flex gap-1 border-b border-gray-800">
            <button @click="propertiesTab = 'inputs'" class="px-3 py-1 text-xs rounded-t transition-colors" :class="propertiesTab === 'inputs' ? 'bg-gray-800 text-gray-50' : 'text-gray-500 hover:text-gray-300'">
              Inputs
            </button>
            <button v-if="isStepLLM || isStepAgent || isStepIf || isStepAskUser" @click="propertiesTab = 'prompt'" class="px-3 py-1 text-xs rounded-t transition-colors" :class="propertiesTab === 'prompt' ? 'bg-gray-800 text-gray-50' : 'text-gray-500 hover:text-gray-300'">
              Prompt
            </button>
            <button v-if="isStepEndpoint" @click="propertiesTab = 'endpoint'" class="px-3 py-1 text-xs rounded-t transition-colors" :class="propertiesTab === 'endpoint' ? 'bg-gray-800 text-gray-50' : 'text-gray-500 hover:text-gray-300'">
              Endpoint
            </button>
            <button v-if="isStepLLM || isStepEndpoint || isStepAgent" @click="propertiesTab = 'structure'" class="px-3 py-1 text-xs rounded-t transition-colors" :class="propertiesTab === 'structure' ? 'bg-gray-800 text-gray-50' : 'text-gray-500 hover:text-gray-300'">
              Structure
            </button>
            <button v-if="!isStepIf" @click="propertiesTab = 'process'" class="px-3 py-1 text-xs rounded-t transition-colors" :class="propertiesTab === 'process' ? 'bg-gray-800 text-gray-50' : 'text-gray-500 hover:text-gray-300'">
              Process
            </button>
          </div>

          <!-- Inputs tab: show tool's request_inputs with add/remove -->
          <div v-if="propertiesTab === 'inputs'">
            <div class="flex items-center justify-between mb-2">
              <div class="text-xs text-gray-500 uppercase font-medium">Inputs</div>
              <button @click="addStepInput" class="text-xs text-blue-400 hover:text-blue-300">+ Add</button>
            </div>
            <div v-if="selectedStep.tool.request_inputs?.length" class="space-y-2">
              <div v-for="(inp, idx) in selectedStep.tool.request_inputs" :key="idx" class="space-y-1 p-2 bg-gray-800/50 rounded border border-gray-800">
                <div class="flex items-center gap-1">
                  <input v-model="inp.name" placeholder="Name" class="flex-1 px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" />
                  <button @click="configInput = inp; showInputConfig = true" type="button" title="Configure input" class="shrink-0 p-1 text-gray-500 hover:text-gray-300 transition-colors">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z" /><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
                  </button>
                  <button v-if="!inp.locked" @click="removeStepInput(idx)" class="text-red-400 hover:text-red-300 text-xs">x</button>
                </div>
                <DynamicInput v-model="inp.value" :type="inp.type" :data="inp.data" :placeholder="'{{ ' + inp.name + ' }}'" :label="inp.name" :variables="pipelineTemplateVariables" />
              </div>
            </div>
            <div v-else class="text-xs text-gray-500">No inputs defined. Click + Add to create one.</div>
          </div>

          <!-- Prompt tab (LLM / Agent / If) -->
          <div v-if="propertiesTab === 'prompt' && (isStepLLM || isStepAgent || isStepIf || isStepAskUser)" class="space-y-3">
            <div v-if="isStepAgent || isStepIf || isStepAskUser">
              <label class="block text-xs text-gray-400 mb-1">System Prompt</label>
              <TemplateInput v-model="selectedStep.tool.system_prompt" :variables="pipelineTemplateVariables" mode="textarea" :rows="3" inputClass="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">Prompt</label>
              <TemplateInput v-model="selectedStep.tool.prompt" :variables="pipelineTemplateVariables" mode="textarea" :rows="6" inputClass="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">Model</label>
              <ModelSelectDropdown v-model="selectedStep.tool.model" :models="models" />
            </div>
          </div>

          <!-- Endpoint tab -->
          <div v-if="propertiesTab === 'endpoint' && isStepEndpoint" class="space-y-3">
            <div class="grid grid-cols-3 gap-2">
              <div>
                <label class="block text-xs text-gray-400 mb-1">Method</label>
                <select v-model.number="selectedStep.tool.endpoint_method" class="w-full px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500">
                  <option :value="0">GET</option>
                  <option :value="1">POST</option>
                  <option :value="2">PUT</option>
                  <option :value="3">DELETE</option>
                </select>
              </div>
              <div class="col-span-2">
                <label class="block text-xs text-gray-400 mb-1">URL</label>
                <TemplateInput v-model="selectedStep.tool.endpoint_url" :variables="pipelineTemplateVariables" mode="input" placeholder="https://..." inputClass="w-full px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" />
              </div>
            </div>
            <KeyValueEditor v-model="stepEndpointQuery" :variables="pipelineTemplateVariables" label="Query Params" keyPlaceholder="param" valuePlaceholder="value" />
            <KeyValueEditor v-model="stepEndpointHeaders" :variables="pipelineTemplateVariables" label="Headers" keyPlaceholder="Header-Name" valuePlaceholder="Header value" />
            <KeyValueEditor v-if="stepEndpointHasBody" v-model="stepEndpointBody" :variables="pipelineTemplateVariables" label="Body" keyPlaceholder="key" valuePlaceholder="value" />
            <div>
              <label class="block text-xs text-gray-400 mb-1">Timeout (seconds)</label>
              <input v-model.number="selectedStep.tool.endpoint_timeout" type="number" min="1" class="w-full px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" />
            </div>
          </div>

          <!-- Structure tab (LLM / Endpoint / Agent) -->
          <div v-if="propertiesTab === 'structure' && (isStepLLM || isStepEndpoint || isStepAgent)" class="space-y-2">
            <p class="text-xs text-gray-600">Define expected output fields for dot-notation access and structured LLM output.</p>
            <ResponseStructureEditor v-model="selectedStep.tool.response_structure" />
          </div>

          <!-- Pre/Post Process tab -->
          <div v-if="propertiesTab === 'process'" class="space-y-3">
            <div>
              <label class="block text-xs text-gray-400 mb-1">Pre-Process (JS)</label>
              <CodeEditor v-model="selectedStep.pre_process" language="javascript" height="150px" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">Post-Process (JS)</label>
              <CodeEditor v-model="selectedStep.post_process" language="javascript" height="150px" />
            </div>
          </div>
        </div>

        <!-- Retry on failure -->
        <div v-if="showStepRetry" class="mt-4 border-t border-gray-800 pt-4 space-y-2">
          <div class="flex items-center justify-between">
            <label class="text-xs text-gray-400">Retry on failure</label>
            <button @click="selectedStep.retry_enabled = !selectedStep.retry_enabled"
              class="relative w-8 h-4 rounded-full transition-colors"
              :class="selectedStep.retry_enabled ? 'bg-blue-600' : 'bg-gray-700'">
              <span class="absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white transition-transform"
                :class="selectedStep.retry_enabled ? 'translate-x-4' : ''"></span>
            </button>
          </div>
          <div v-if="selectedStep.retry_enabled" class="flex items-center justify-between">
            <label class="text-xs text-gray-500">Max retries</label>
            <input v-model.number="selectedStep.max_retries" type="number" min="1" max="10"
              class="w-16 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs text-gray-200 focus:outline-none focus:border-blue-500 text-right" />
          </div>
        </div>

        <!-- Validate output -->
        <div v-if="showStepValidation" class="mt-4 border-t border-gray-800 pt-4 space-y-2">
          <div class="flex items-center justify-between">
            <label class="text-xs text-gray-400">Validate output</label>
            <button @click="selectedStep.validation_enabled = !selectedStep.validation_enabled"
              class="relative w-8 h-4 rounded-full transition-colors"
              :class="selectedStep.validation_enabled ? 'bg-green-600' : 'bg-gray-700'">
              <span class="absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white transition-transform"
                :class="selectedStep.validation_enabled ? 'translate-x-4' : ''"></span>
            </button>
          </div>
          <div v-if="selectedStep.validation_enabled">
            <label class="block text-xs text-gray-500 mb-1">Validation model <span class="text-gray-600">(optional, overrides pipeline default)</span></label>
            <ModelSelectDropdown v-model="selectedStep.validation_model" :models="models" />
          </div>
        </div>

        <!-- Delete button -->
        <button v-if="!isStepStart" @click="deleteStep" class="w-full px-3 py-1.5 bg-red-900/30 text-red-400 rounded text-sm hover:bg-red-900/50 transition-colors mt-4">
          Delete Step
        </button>
      </div>
    </div>
    <!-- Run inputs modal -->
    <Teleport to="body">
      <div v-if="showRunModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" @click.self="showRunModal = false">
        <div class="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
          <h2 class="text-lg font-bold text-gray-50">Run Pipeline</h2>
          <p class="text-sm text-gray-400">Enter values for the pipeline inputs.</p>
          <div v-if="runInputs.length === 0" class="text-sm text-gray-500">No inputs defined.</div>
          <div v-for="(inp, idx) in runInputs" :key="idx" class="space-y-1">
            <label class="block text-sm text-gray-300">{{ inp.name || `Input ${idx + 1}` }}</label>
            <DynamicInput v-model="inp.value" :type="inp.type" :data="inp.data" :placeholder="inp.name" :label="inp.name" />
          </div>
          <div class="flex gap-3 pt-2">
            <button @click="confirmRun" class="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium transition-colors">
              Run
            </button>
            <button @click="showRunModal = false" class="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors">
              Cancel
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <InputConfigModal v-model="showInputConfig" :input="configInput" />

    <!-- AI Assist Dialog -->
    <Teleport to="body">
      <div v-if="showAiAssist" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/60" @click="closeAiAssist"></div>
        <div class="relative bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-[640px] max-h-[80vh] flex flex-col">
          <!-- Dialog header -->
          <div class="flex items-center justify-between px-5 py-4 border-b border-gray-800">
            <div class="flex items-center gap-2">
              <svg class="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
              <h2 class="text-lg font-bold text-gray-100">AI Assist</h2>
            </div>
            <button @click="closeAiAssist" class="text-gray-500 hover:text-gray-300 transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          </div>

          <!-- Dialog body -->
          <div class="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            <!-- Model selector -->
            <div>
              <label class="block text-xs text-gray-400 mb-1">Model</label>
              <ModelSelectDropdown v-model="aiAssistModel" :models="models" />
            </div>

            <!-- Description -->
            <div>
              <label class="block text-xs text-gray-400 mb-1">Describe the pipeline you want to build</label>
              <textarea
                v-model="aiAssistDescription"
                rows="3"
                placeholder="e.g. Build a pipeline that takes a topic, generates a blog post outline, then writes each section, and combines them into a final article..."
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-purple-500 resize-y"
                :disabled="aiAssistLoading || aiAssistPhase !== 'input'"
                @keydown.ctrl.enter="generatePipelineWithAi('clarify')"
              ></textarea>
            </div>

            <!-- Clarification questions -->
            <div v-if="aiAssistPhase === 'questions' && aiAssistQuestions.length" class="space-y-3">
              <div class="flex items-center gap-2 text-sm text-purple-300">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                A few questions to help build a better pipeline:
              </div>
              <div v-for="q in aiAssistQuestions" :key="q.id" class="bg-gray-800/50 border border-gray-700/50 rounded-lg p-3 space-y-2">
                <label class="block text-sm text-gray-200">{{ q.text }}</label>
                <div v-if="q.type === 'choice' && q.options?.length">
                  <select v-model="aiAssistAnswers[q.id]" class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-purple-500">
                    <option v-for="opt in q.options" :key="opt" :value="opt">{{ opt }}</option>
                  </select>
                </div>
                <div v-else>
                  <input
                    v-model="aiAssistAnswers[q.id]"
                    type="text"
                    class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-purple-500"
                    placeholder="Your answer..."
                    @keydown.enter.prevent
                  />
                </div>
              </div>
            </div>

            <!-- Streaming output area -->
            <div v-if="aiAssistStatus || aiAssistStreamJson" class="space-y-2">
              <!-- Status indicator -->
              <div v-if="aiAssistLoading" class="flex items-center gap-2 text-sm text-purple-300">
                <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                {{ aiAssistStatus }}
              </div>
              <div v-else-if="aiAssistStatus === 'Done'" class="flex items-center gap-2 text-sm text-green-400">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
                Generation complete
                <span v-if="aiAssistUsage" class="text-xs text-gray-500 ml-2">
                  {{ aiAssistUsage.input_tokens.toLocaleString() }} in / {{ aiAssistUsage.output_tokens.toLocaleString() }} out
                  <span v-if="aiAssistUsage.cost"> &middot; ${{ aiAssistUsage.cost.toFixed(4) }}</span>
                </span>
              </div>

              <!-- Streaming JSON display -->
              <div v-if="aiAssistStreamJson" class="relative">
                <div class="text-xs text-gray-500 mb-1">Generated Configuration</div>
                <pre class="bg-gray-950 border border-gray-800 rounded-lg p-3 text-xs text-gray-300 font-mono overflow-auto max-h-64 whitespace-pre-wrap">{{ aiAssistStreamJson }}</pre>
              </div>
            </div>
          </div>

          <!-- Dialog footer -->
          <div class="px-5 py-3 border-t border-gray-800 flex items-center gap-2 justify-end">
            <button
              @click="closeAiAssist"
              class="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
            >
              Cancel
            </button>
            <button
              v-if="aiAssistResult"
              @click="applyAiPipelineResult"
              class="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-medium transition-colors"
            >
              Apply to Pipeline
            </button>
            <template v-else-if="aiAssistPhase === 'questions'">
              <button
                @click="submitClarificationAnswers"
                class="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-medium transition-colors"
              >
                Submit Answers
              </button>
            </template>
            <template v-else-if="aiAssistPhase === 'input'">
              <button
                @click="generatePipelineWithAi('generate')"
                :disabled="aiAssistLoading || !aiAssistDescription.trim()"
                class="px-4 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm transition-colors"
                title="Skip questions and generate directly"
              >
                Quick Generate
              </button>
              <button
                @click="generatePipelineWithAi('clarify')"
                :disabled="aiAssistLoading || !aiAssistDescription.trim()"
                class="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition-colors"
              >
                {{ aiAssistLoading ? 'Analyzing...' : 'Generate' }}
              </button>
            </template>
            <template v-else-if="aiAssistPhase === 'generating' && aiAssistLoading">
              <button disabled class="px-4 py-2 bg-purple-600/50 rounded-lg text-sm font-medium cursor-not-allowed">
                Generating...
              </button>
            </template>
          </div>
        </div>
      </div>
    </Teleport>

    <ExportModal
      v-model="showExportModal"
      :defaultName="pipeline.name"
      :defaultDescription="pipeline.description"
      :defaultVersion="pipeline.export_version || 1"
      @confirm="onExportConfirm"
    />
  </div>
</template>
