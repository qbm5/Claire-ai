<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, computed, markRaw, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/controls/dist/style.css'
import { PathFindingEdge } from '@vue-flow/pathfinding-edge'
import { stopPipelineRun, rerunFromStep, resumePipelineRun, respondToStep, updateStepOutput } from '@/services/pipelineService'
import { onEvent } from '@/services/eventBus'
import { PipelineStatusType, StatusLabels, StatusColors, ToolType, type AiPipelineRun, type AiPipelineStep, type AiPipelineMemory } from '@/models'
import { get, API_BASE } from '@/services/api'
import { useModels, loadModels } from '@/composables/useModels'
import StepNode from '@/components/pipeline/StepNode.vue'
import MemoryNode from '@/components/pipeline/MemoryNode.vue'
import RunLogViewer from '@/components/pipeline/RunLogViewer.vue'
import { useTheme } from '@/composables/useTheme'
import { renderMarkdown, renderMarkdownToolResult, renderArtifactTray } from '@/composables/useArtifactRenderer'

const { theme } = useTheme()
const nodeTypes = { step: markRaw(StepNode), memory: markRaw(MemoryNode) } as any
const edgeTypes = { pathfinding: markRaw(PathFindingEdge) } as any

const props = defineProps<{ id: string }>()
const router = useRouter()

const { models } = useModels()
const run = ref<AiPipelineRun | null>(null)
const stepStreams = ref<Record<string, string>>({})
const stepArtifacts = ref<Record<string, Array<{ filename: string; url: string; mime: string; size: number }>>>({})
const selectedIteration = ref<Record<string, number>>({})
const iterationProgress = ref<Record<string, {
  total: number
  activeIndex: number
  completed: { index: number; input: string; output: string; agent_output?: string; cost?: any[] }[]
}>>({})
const selectedExecution = ref<Record<string, number>>({})  // step_id -> index (-1 = current/latest)
const liveIterationSelected = ref<Record<string, number>>({})  // step_id -> which iteration button is selected during live
const loading = ref(true)
const rateLimitMsg = ref('')
const askUserQuestions = ref<Record<string, { questions: any[]; round: number }>>({})
const askUserAnswers = ref<Record<string, Record<string, string>>>({})
const fileUploadRequests = ref<Record<string, { message: string }>>({})
const pendingUploadFiles = ref<Record<string, File[]>>({})
const uploading = ref<Record<string, boolean>>({})
const selectedMemoryId = ref<string | null>(null)
let rateLimitTimer: ReturnType<typeof setTimeout> | null = null
let pollTimer: ReturnType<typeof setTimeout> | null = null

const statusLabels = StatusLabels
const statusColors = StatusColors

let cleanups: (() => void)[] = []

// Reset state when navigating to a different run (rerun from here)
watch(() => props.id, () => {
  run.value = null
  stepStreams.value = {}
  selectedIteration.value = {}
  iterationProgress.value = {}
  selectedExecution.value = {}
  liveIterationSelected.value = {}
  selectedStepId.value = null
  selectedMemoryId.value = null
  stopping.value = false
  rateLimitMsg.value = ''
  askUserQuestions.value = {}
  askUserAnswers.value = {}
  fileUploadRequests.value = {}
  pendingUploadFiles.value = {}
  uploading.value = {}
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
  pollRun()
})

onMounted(async () => {
  await loadModels()
  loading.value = false

  // Subscribe to SSE events
  cleanups.push(onEvent('step_start', (data: any) => {
    if (data.run_id !== props.id) return
    selectedStepId.value = data.step_id
    if (run.value) {
      const step = run.value.steps.find(s => s.id === data.step_id)
      if (step) step.status = PipelineStatusType.Running
      run.value.steps = [...run.value.steps]
    }
  }))

  cleanups.push(onEvent('step_stream', (data: any) => {
    if (data.run_id !== props.id) return
    const ip = iterationProgress.value[data.step_id]
    if (ip) {
      // Route to per-iteration stream key
      const iterKey = data.step_id + '_iter_' + ip.activeIndex
      stepStreams.value[iterKey] = (stepStreams.value[iterKey] || '') + data.text
    } else {
      stepStreams.value[data.step_id] = (stepStreams.value[data.step_id] || '') + data.text
    }
  }))

  cleanups.push(onEvent('step_complete', (data: any) => {
    if (data.run_id !== props.id) return
    if (run.value) {
      const step = run.value.steps.find(s => s.id === data.step_id)
      if (step) {
        step.status = PipelineStatusType.Completed
        step.outputs = [{ name: step.name, value: data.output }]
        if (data.agent_output) {
          step.outputs.push({ name: step.name + '_agent', value: data.agent_output })
        }
        step.call_cost = data.cost || []
        if (data.artifacts?.length) {
          stepArtifacts.value[data.step_id] = data.artifacts
        }
        if (data.split_count > 1) {
          step.split_count = data.split_count
          step.iteration_outputs = data.iteration_outputs
        }
        if (data.prompt_used) {
          step.prompt_used = data.prompt_used
        }
        if (data.resolved_inputs?.length) {
          step.resolved_inputs = data.resolved_inputs
        }
        // Clear streaming text and iteration progress
        delete stepStreams.value[data.step_id]
        // Clear all per-iteration stream keys for this step
        for (const key of Object.keys(stepStreams.value)) {
          if (key.startsWith(data.step_id + '_iter_')) delete stepStreams.value[key]
        }
        delete iterationProgress.value[data.step_id]
        delete liveIterationSelected.value[data.step_id]
      }
      run.value.steps = [...run.value.steps]
    }
  }))

  cleanups.push(onEvent('step_split', (data: any) => {
    if (data.run_id !== props.id) return
    iterationProgress.value[data.step_id] = { total: data.total, activeIndex: 0, completed: [] }
    liveIterationSelected.value[data.step_id] = 0
    // Set split_count on the live step so UI shows count immediately
    if (run.value) {
      const step = run.value.steps.find(s => s.id === data.step_id)
      if (step) step.split_count = data.total
    }
  }))

  cleanups.push(onEvent('iteration_start', (data: any) => {
    if (data.run_id !== props.id) return
    const ip = iterationProgress.value[data.step_id]
    if (ip) {
      ip.activeIndex = data.index
      // Auto-select the active iteration
      liveIterationSelected.value[data.step_id] = data.index
    }
  }))

  cleanups.push(onEvent('iteration_complete', (data: any) => {
    if (data.run_id !== props.id) return
    const ip = iterationProgress.value[data.step_id]
    if (ip) {
      ip.completed.push({
        index: data.index,
        input: data.input || '',
        output: data.output || '',
        agent_output: data.agent_output,
        cost: data.cost,
      })
      // Clear per-iteration streaming text
      delete stepStreams.value[data.step_id + '_iter_' + data.index]
    }
  }))

  cleanups.push(onEvent('step_validating', (data: any) => {
    if (data.run_id !== props.id) return
    if (run.value) {
      const step = run.value.steps.find(s => s.id === data.step_id)
      if (step) step.status_text = 'Validating output...'
      run.value.steps = [...run.value.steps]
    }
  }))

  cleanups.push(onEvent('step_error', (data: any) => {
    if (data.run_id !== props.id) return
    if (run.value) {
      const step = run.value.steps.find(s => s.id === data.step_id)
      if (step) {
        step.status = PipelineStatusType.Failed
        step.status_text = data.error
        if (data.cost?.length) step.call_cost = data.cost
      }
      run.value.steps = [...run.value.steps]
    }
  }))

  cleanups.push(onEvent('pipeline_paused', (data: any) => {
    if (data.run_id !== props.id) return
    if (run.value) run.value.status = PipelineStatusType.Paused
  }))

  cleanups.push(onEvent('pipeline_complete', (data: any) => {
    if (data.run_id !== props.id) return
    stopping.value = false
    // Fetch final state from server
    fetchRun()
  }))

  cleanups.push(onEvent('rate_limit', (data: any) => {
    rateLimitMsg.value = `Rate limited — retrying in ${data.retry_after}s (attempt ${data.attempt}/${data.max_retries})`
    if (rateLimitTimer) clearTimeout(rateLimitTimer)
    rateLimitTimer = setTimeout(() => { rateLimitMsg.value = '' }, data.retry_after * 1000)
  }))

  cleanups.push(onEvent('ask_user', (data: any) => {
    if (data.run_id !== props.id) return
    askUserQuestions.value[data.step_id] = { questions: data.questions, round: data.round }
    askUserAnswers.value[data.step_id] = {}
    for (const q of data.questions) {
      askUserAnswers.value[data.step_id][q.id] = q.type === 'choice' && q.options?.length ? q.options[0] : ''
    }
    if (run.value) run.value.status = PipelineStatusType.WaitingForInput
  }))

  cleanups.push(onEvent('ask_user_answered', (data: any) => {
    if (data.run_id !== props.id) return
    delete askUserQuestions.value[data.step_id]
    if (run.value) run.value.status = PipelineStatusType.Running
  }))

  cleanups.push(onEvent('file_upload_request', (data: any) => {
    if (data.run_id !== props.id) return
    fileUploadRequests.value[data.step_id] = { message: data.message }
    pendingUploadFiles.value[data.step_id] = []
    selectedStepId.value = data.step_id
    selectedMemoryId.value = null
    if (run.value) run.value.status = PipelineStatusType.WaitingForInput
  }))

  cleanups.push(onEvent('file_upload_complete', (data: any) => {
    if (data.run_id !== props.id) return
    delete fileUploadRequests.value[data.step_id]
    delete pendingUploadFiles.value[data.step_id]
    delete uploading.value[data.step_id]
    if (run.value) run.value.status = PipelineStatusType.Running
  }))

  cleanups.push(onEvent('memory_update', (data: any) => {
    if (data.run_id !== props.id || !run.value) return
    const mem = (run.value.memories || []).find((m: any) => m.id === data.memory_id)
    if (mem && data.latest) {
      // Append latest messages
      for (const msg of data.latest) {
        if (!mem.messages.some((m: any) => m.timestamp === msg.timestamp && m.role === msg.role && m.step_name === msg.step_name)) {
          mem.messages.push(msg)
        }
      }
    }
  }))

  // Start polling
  pollRun()
})

async function fetchRun() {
  try {
    const data = await get<AiPipelineRun>(`/pipelines/runs/${props.id}`)
    if (data && data.id) {
      run.value = data
      // Auto-select first running/waiting/completed step if none selected
      if (!selectedStepId.value) {
        const activeStep = data.steps.find(s => s.status === PipelineStatusType.Running)
          || data.steps.find(s => s.status === PipelineStatusType.WaitingForInput)
          || data.steps.find(s => s.status === PipelineStatusType.Completed)
        if (activeStep) selectedStepId.value = activeStep.id
      }
      // Populate stepArtifacts from persisted step data
      for (const step of data.steps) {
        if ((step as any).artifacts?.length) {
          stepArtifacts.value[step.id] = (step as any).artifacts
        }
      }
      // Re-populate fileUploadRequests from polled data when a FileUpload step is waiting
      if (data.status === PipelineStatusType.WaitingForInput) {
        for (const step of data.steps) {
          if (step.tool?.type === ToolType.FileUpload && step.status === PipelineStatusType.Running && !fileUploadRequests.value[step.id]) {
            fileUploadRequests.value[step.id] = { message: step.tool.prompt || 'Upload file(s)' }
            pendingUploadFiles.value[step.id] = []
            selectedStepId.value = step.id
            selectedMemoryId.value = null
          }
        }
      }
    }
  } catch {}
}

async function pollRun() {
  await fetchRun()

  // Only continue polling if still running or not yet loaded
  const status = run.value?.status
  const isActive = status === PipelineStatusType.Running || status === PipelineStatusType.Pending || status === PipelineStatusType.WaitingForInput
  if (isActive || !run.value) {
    pollTimer = setTimeout(pollRun, 2000)
  }
}

onUnmounted(() => {
  cleanups.forEach(fn => fn())
  if (pollTimer) clearTimeout(pollTimer)
  if (rateLimitTimer) clearTimeout(rateLimitTimer)
})

const stopping = ref(false)

async function stop() {
  if (stopping.value) return
  stopping.value = true
  await stopPipelineRun(props.id)
}

async function resume() {
  try {
    await resumePipelineRun(props.id)
    if (run.value) run.value.status = PipelineStatusType.Running
    pollRun()
  } catch (e) {
    console.error('Resume failed', e)
  }
}

async function submitAnswers(stepId: string) {
  const answers = Object.entries(askUserAnswers.value[stepId] || {})
    .map(([id, answer]) => ({ id, answer }))
  await respondToStep(props.id, stepId, answers)
}

function onUploadDrop(stepId: string, e: DragEvent) {
  e.preventDefault()
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length) {
    pendingUploadFiles.value[stepId] = [...(pendingUploadFiles.value[stepId] || []), ...files]
  }
}

function onUploadSelect(stepId: string, e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (files.length) {
    pendingUploadFiles.value[stepId] = [...(pendingUploadFiles.value[stepId] || []), ...files]
  }
  input.value = ''
}

function removeUploadFile(stepId: string, idx: number) {
  pendingUploadFiles.value[stepId]?.splice(idx, 1)
}

async function submitUpload(stepId: string) {
  const files = pendingUploadFiles.value[stepId]
  if (!files?.length) return
  uploading.value[stepId] = true
  try {
    const formData = new FormData()
    for (const file of files) formData.append('files', file)
    const res = await fetch(`${API_BASE}/upload/${props.id}`, { method: 'POST', body: formData })
    const data = await res.json()
    const fileNames = (data.files || []).join(',')
    await respondToStep(props.id, stepId, [{ id: 'files', answer: fileNames }])
  } catch (e) {
    console.error('Upload failed', e)
  } finally {
    uploading.value[stepId] = false
  }
}


function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

async function rerun(stepId: string) {
  try {
    const newRun = await rerunFromStep(props.id, stepId)
    if (newRun?.id) {
      router.push(`/pipeline-run/${newRun.id}`)
    }
  } catch (e) {
    console.error('Rerun failed', e)
  }
}

// ── Edit step output while paused ──
const editingStepId = ref<string | null>(null)
const editedOutputValue = ref('')
const savingOutput = ref(false)

function startEditOutput(stepId: string, currentValue: string) {
  editingStepId.value = stepId
  editedOutputValue.value = currentValue
}

function cancelEditOutput() {
  editingStepId.value = null
  editedOutputValue.value = ''
}

async function saveEditOutput() {
  if (!editingStepId.value || savingOutput.value) return
  savingOutput.value = true
  try {
    await updateStepOutput(props.id, editingStepId.value, editedOutputValue.value)
    // Update local state
    if (run.value) {
      const step = run.value.steps.find(s => s.id === editingStepId.value)
      if (step?.outputs?.length) {
        step.outputs[0].value = editedOutputValue.value
      }
    }
    editingStepId.value = null
    editedOutputValue.value = ''
  } catch (e: any) {
    console.error('Failed to save output', e)
  } finally {
    savingOutput.value = false
  }
}

const selectedStepId = ref<string | null>(null)

const selectedStep = computed(() => {
  if (!run.value || !selectedStepId.value) return null
  return run.value.steps.find(s => s.id === selectedStepId.value) ?? null
})

function selectStep(id: string) {
  cancelEditOutput()
  // Check if it's a memory node
  const mem = (run.value?.memories || []).find((m: any) => m.id === id)
    || (run.value?.pipeline_snapshot?.memories || []).find((m: any) => m.id === id)
  if (mem) {
    selectedMemoryId.value = id
    selectedStepId.value = null
    return
  }
  selectedStepId.value = id
  selectedMemoryId.value = null
}

const selectedMemory = computed(() => {
  if (!run.value || !selectedMemoryId.value) return null
  // Get runtime messages from run.memories, falling back to snapshot
  const runtime = (run.value.memories || []).find((m: any) => m.id === selectedMemoryId.value)
  if (runtime) return runtime
  const snapshot = (run.value.pipeline_snapshot?.memories || []).find((m: any) => m.id === selectedMemoryId.value)
  return snapshot ? { ...snapshot, messages: [] } : null
})

// Computed step data: either current execution or a historical one
const viewedStepData = computed(() => {
  if (!selectedStep.value) return null
  const step = selectedStep.value
  const execIdx = selectedExecution.value[step.id]
  if (execIdx !== undefined && execIdx >= 0 && step.execution_history?.[execIdx]) {
    return step.execution_history[execIdx]
  }
  // Latest/current execution
  return {
    outputs: step.outputs,
    call_cost: step.call_cost,
    iteration_outputs: step.iteration_outputs,
    split_count: step.split_count,
    status_text: step.status_text,
    prompt_used: step.prompt_used,
    resolved_inputs: step.resolved_inputs,
  }
})

const canEditOutput = computed(() => {
  if (!run.value || !selectedStep.value) return false
  return run.value.status === PipelineStatusType.Paused
    && selectedStep.value.status === PipelineStatusType.Completed
    && (selectedExecution.value[selectedStep.value.id] === undefined || selectedExecution.value[selectedStep.value.id] === -1)
})

const copiedKey = ref('')
let copiedTimer: ReturnType<typeof setTimeout> | null = null

async function copyText(text: string, key: string) {
  await navigator.clipboard.writeText(text)
  copiedKey.value = key
  if (copiedTimer) clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { copiedKey.value = '' }, 1500)
}

function renderMd(text: string, stepId?: string): string {
  let html = renderMarkdown(text)
  // Append artifact tray for unreferenced artifacts
  if (stepId) {
    const artifacts = stepArtifacts.value[stepId]
    if (artifacts?.length) {
      html += renderArtifactTray(artifacts, text)
    }
  }
  return html
}

const isRunFinished = computed(() => {
  if (!run.value) return false
  const s = run.value.status
  return s === PipelineStatusType.Completed || s === PipelineStatusType.Failed || s === PipelineStatusType.Paused
})

function stepCost(callCost: any[]) {
  if (!callCost?.length) return 0
  return callCost.reduce((acc, c) => {
    const m = models.value.find(x => x.id === c.model)
    const inCost = m ? (c.input_token_count / 1_000_000) * m.input_cost : 0
    const outCost = m ? (c.output_token_count / 1_000_000) * m.output_cost : 0
    return acc + inCost + outCost
  }, 0)
}

// Sort steps by graph traversal order (following next_steps from start)
interface StepListItem {
  step: AiPipelineStep
  indent: number
  branchLabel?: string
}

const orderedSteps = computed((): StepListItem[] => {
  if (!run.value) return []
  const steps = run.value.steps
  const byId = new Map(steps.map(s => [s.id, s]))
  const result: StepListItem[] = []
  const visited = new Set<string>()

  function getNextIds(step: AiPipelineStep): string[] {
    return [...(step.next_steps || []), ...(step.next_steps_true || []), ...(step.next_steps_false || [])]
  }

  function getAllReachable(startId: string): Set<string> {
    const reachable = new Set<string>()
    const q = [startId]
    while (q.length) {
      const id = q.shift()!
      if (reachable.has(id)) continue
      reachable.add(id)
      const s = byId.get(id)
      if (s) for (const nid of getNextIds(s)) q.push(nid)
    }
    return reachable
  }

  function findMergePoint(branchStartIds: string[]): string | null {
    if (branchStartIds.length < 2) return null
    const sets = branchStartIds.map(id => getAllReachable(id))
    let common = new Set(sets[0])
    for (let i = 1; i < sets.length; i++) {
      common = new Set([...common].filter(x => sets[i].has(x)))
    }
    if (common.size === 0) return null
    // BFS from all branch starts to find the topologically closest common node
    const q = [...branchStartIds]
    const seen = new Set<string>()
    while (q.length) {
      const id = q.shift()!
      if (seen.has(id)) continue
      seen.add(id)
      if (common.has(id)) return id
      const s = byId.get(id)
      if (s) for (const nid of getNextIds(s)) q.push(nid)
    }
    return null
  }

  function getBranchLabels(step: AiPipelineStep, nextIds: string[]): string[] {
    const isIf = step.tool?.type === ToolType.If
    if (isIf) {
      const trueIds = step.next_steps_true || []
      return nextIds.map(id => trueIds.includes(id) ? 'True' : 'False')
    }
    const letters = 'ABCDEFGH'
    return nextIds.map((_, i) => `Path ${letters[i] || i + 1}`)
  }

  function traverse(stepId: string, indent: number, stopAt: string | null) {
    if (visited.has(stepId) || stepId === stopAt) return
    const step = byId.get(stepId)
    if (!step) return
    visited.add(stepId)
    result.push({ step, indent })

    const nextIds = getNextIds(step)
    if (nextIds.length > 1) {
      const mergeId = findMergePoint(nextIds)
      const labels = getBranchLabels(step, nextIds)
      for (let i = 0; i < nextIds.length; i++) {
        if (visited.has(nextIds[i]) || nextIds[i] === mergeId) continue
        traverseBranch(nextIds[i], indent + 1, mergeId, labels[i])
      }
      if (mergeId) traverse(mergeId, indent, stopAt)
    } else if (nextIds.length === 1) {
      traverse(nextIds[0], indent, stopAt)
    }
  }

  function traverseBranch(stepId: string, indent: number, stopAt: string | null, label?: string) {
    if (visited.has(stepId) || stepId === stopAt) return
    const step = byId.get(stepId)
    if (!step) return
    visited.add(stepId)
    result.push({ step, indent, branchLabel: label })

    const nextIds = getNextIds(step)
    if (nextIds.length > 1) {
      // Nested fork within branch
      const mergeId = findMergePoint(nextIds)
      const labels = getBranchLabels(step, nextIds)
      for (let i = 0; i < nextIds.length; i++) {
        if (visited.has(nextIds[i]) || nextIds[i] === mergeId) continue
        traverseBranch(nextIds[i], indent + 1, mergeId, labels[i])
      }
      if (mergeId && mergeId !== stopAt) traverseBranch(mergeId, indent, stopAt)
    } else if (nextIds.length === 1) {
      traverseBranch(nextIds[0], indent, stopAt)
    }
  }

  const startSteps = steps.filter(s => s.is_start)
  if (startSteps.length === 0 && steps.length > 0) startSteps.push(steps[0])

  if (startSteps.length > 1) {
    // Multiple start steps = initial parallel fork
    const mergeId = findMergePoint(startSteps.map(s => s.id))
    const letters = 'ABCDEFGH'
    startSteps.forEach((s, i) => {
      if (!visited.has(s.id)) traverseBranch(s.id, 1, mergeId, `Path ${letters[i]}`)
    })
    if (mergeId) traverse(mergeId, 0, null)
  } else if (startSteps.length === 1) {
    traverse(startSteps[0].id, 0, null)
  }

  // Append orphaned steps
  for (const step of steps) {
    if (!visited.has(step.id)) result.push({ step, indent: 0 })
  }

  return result
})

const totalCost = computed(() => {
  if (!run.value) return 0
  return run.value.steps.reduce((acc, s) => acc + stepCost(s.call_cost || []), 0)
})

// ── Flow Graph ─────────────────────────────────────────────────────

const stepListRefs = ref<Record<string, HTMLElement>>({})

// ── Resizable 3-panel layout (percentages) ──
const containerRef = ref<HTMLElement | null>(null)
const topPercent = ref(20)     // Vue Flow
const bottomPercent = ref(15)  // Execution Log
const logExpanded = ref(true)
const midPercent = computed(() => 100 - topPercent.value - bottomPercent.value)
const MIN_PANEL = 10

function onDragTop(e: MouseEvent) {
  e.preventDefault()
  const container = containerRef.value
  if (!container) return
  const startY = e.clientY
  const startTop = topPercent.value
  const containerH = container.clientHeight
  function onMove(ev: MouseEvent) {
    const dpct = ((ev.clientY - startY) / containerH) * 100
    topPercent.value = Math.max(MIN_PANEL, Math.min(100 - bottomPercent.value - MIN_PANEL, startTop + dpct))
  }
  function onUp() {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

function onDragBottom(e: MouseEvent) {
  e.preventDefault()
  const container = containerRef.value
  if (!container) return
  const startY = e.clientY
  const startBottom = bottomPercent.value
  const containerH = container.clientHeight
  function onMove(ev: MouseEvent) {
    const dpct = ((ev.clientY - startY) / containerH) * 100
    bottomPercent.value = Math.max(MIN_PANEL, Math.min(100 - topPercent.value - MIN_PANEL, startBottom - dpct))
  }
  function onUp() {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

const showGraph = computed(() => {
  if (!run.value?.pipeline_snapshot) return false
  const edges = run.value.pipeline_snapshot.edges || []
  if (edges.length <= 1) return false
  return true
})

const flowNodes = computed(() => {
  if (!run.value?.pipeline_snapshot) return []
  const snapshot = run.value.pipeline_snapshot
  const runStepMap = new Map(run.value.steps.map(s => [s.id, s]))

  const nodes = snapshot.steps.map(s => {
    const runStep = runStepMap.get(s.id)
    return {
      id: s.id,
      type: 'step',
      position: { x: s.pos_x ?? 0, y: s.pos_y ?? 0 },
      data: { ...s, status: runStep?.status ?? s.status, outputs: runStep?.outputs ?? s.outputs, split_count: runStep?.split_count },
    }
  })

  // Add memory nodes
  const runtimeMemories = new Map((run.value!.memories || []).map((m: any) => [m.id, m]))
  for (const mem of (snapshot.memories || [])) {
    const runtime = runtimeMemories.get(mem.id)
    nodes.push({
      id: mem.id,
      type: 'memory',
      position: { x: mem.pos_x ?? 0, y: mem.pos_y ?? 0 },
      data: runtime || { ...mem, messages: [] },
    })
  }

  return nodes
})

const flowEdges = computed(() => {
  if (!run.value?.pipeline_snapshot) return []
  const snapshot = run.value.pipeline_snapshot
  const runStepMap = new Map(run.value.steps.map(s => [s.id, s]))

  return snapshot.edges.map(e => {
    // Memory edges: dashed sky-blue, no animation
    if ((e.source_handle || '').endsWith('_memory')) {
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.source_handle,
        targetHandle: e.target_handle,
        type: 'pathfinding',
        animated: false,
        style: { stroke: '#38bdf8', strokeWidth: 2, strokeDasharray: '5 3' },
      }
    }

    const sourceStep = runStepMap.get(e.source)
    const targetStep = runStepMap.get(e.target)

    let color = '#4b5563' // gray - not reached yet
    let strokeWidth = 2

    if (sourceStep) {
      const srcStatus = sourceStep.status
      const tgtStatus = targetStep?.status ?? PipelineStatusType.Pending
      const srcDone = srcStatus === PipelineStatusType.Completed
      const srcFailed = srcStatus === PipelineStatusType.Failed
      const srcActive = srcStatus === PipelineStatusType.Running || srcDone || srcStatus === PipelineStatusType.Paused
      const tgtReached = tgtStatus === PipelineStatusType.Running || tgtStatus === PipelineStatusType.Completed || tgtStatus === PipelineStatusType.Paused

      if (srcFailed) {
        color = '#ef4444' // red
      } else if (srcDone && sourceStep.tool?.type === ToolType.If) {
        const ifResult = sourceStep.outputs?.[0]?.value
        const isTrueHandle = e.source_handle?.endsWith('_true')
        const isFalseHandle = e.source_handle?.endsWith('_false')
        if (isTrueHandle || isFalseHandle) {
          const resultIsTrue = ifResult === 'true' || ifResult === true
          const taken = (isTrueHandle && resultIsTrue) || (isFalseHandle && !resultIsTrue)
          if (taken) {
            color = '#22c55e'; strokeWidth = 3
          } else {
            color = '#ef4444'
          }
        } else if (srcDone) {
          color = '#22c55e'; strokeWidth = 3
        }
      } else if (srcDone || tgtReached) {
        // Edge turns green once source is done OR target has started
        color = '#22c55e'; strokeWidth = 3
      }
    }

    const pipelineActive = run.value!.status === PipelineStatusType.Running || run.value!.status === PipelineStatusType.Pending || run.value!.status === PipelineStatusType.WaitingForInput
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.source_handle,
      targetHandle: e.target_handle,
      type: 'pathfinding',
      style: { stroke: color, strokeWidth },
      animated: color === '#22c55e' && pipelineActive,
    }
  })
})

function onNodeClick(event: any) {
  const node = event.node ?? event
  selectStep(node.id)
  if (node.type !== 'memory') {
    nextTick(() => {
      const el = stepListRefs.value[node.id]
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    })
  }
}
</script>

<template>
  <div class="p-6">
    <div class="flex items-center gap-4 mb-6">
      <button @click="router.back()" class="text-gray-400 hover:text-gray-50">&larr; Back</button>
      <h1 class="text-2xl font-bold">Pipeline Run</h1>
      <span v-if="run" class="text-sm font-medium" :class="statusColors[run.status]">
        {{ statusLabels[run.status] }}
      </span>
      <span v-if="rateLimitMsg" class="text-xs px-3 py-1 rounded-full bg-amber-900/50 text-amber-300 border border-amber-700">
        {{ rateLimitMsg }}
      </span>
      <div class="flex-1"></div>
      <span v-if="run" class="text-sm text-gray-400">
        Total: ${{ totalCost.toFixed(6) }}
      </span>
      <span v-if="stopping && run?.status === PipelineStatusType.Running" class="text-xs text-amber-400 animate-pulse">
        Stopping after current operation...
      </span>
      <button v-if="run?.status === PipelineStatusType.Running" @click="stop" :disabled="stopping" class="px-4 py-2 rounded-lg text-sm font-medium transition-colors" :class="stopping ? 'bg-red-900 text-red-300 opacity-75' : 'bg-red-600 hover:bg-red-700'">
        {{ stopping ? 'Stopping...' : 'Stop' }}
      </button>
      <button v-if="run?.status === PipelineStatusType.Paused" @click="resume" class="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium transition-colors">
        Resume
      </button>
    </div>

    <div v-if="loading" class="text-gray-400">Loading...</div>

    <div v-else-if="!run" class="text-center py-20">
      <div class="text-gray-400 mb-2">Loading pipeline run...</div>
      <div class="text-sm text-gray-600">Run ID: {{ id }}</div>
    </div>

    <!-- Resizable 3-panel content area -->
    <div v-if="run" ref="containerRef" class="flex flex-col" style="height: calc(100vh - 168px)">
      <!-- Panel 1: Flow Graph (25%) -->
      <div v-if="showGraph" class="border border-gray-800 rounded-lg overflow-hidden shrink-0" :style="{ height: topPercent + '%' }">
        <VueFlow
          :nodes="flowNodes"
          :edges="flowEdges"
          :node-types="nodeTypes"
          :edge-types="edgeTypes"
          :nodes-draggable="false"
          :nodes-connectable="false"
          :elements-selectable="false"
          :min-zoom="0.1"
          :max-zoom="2"
          :default-viewport="{ x: 0, y: 0, zoom: 0.5 }"
          pan-on-drag
          zoom-on-scroll
          fit-view-on-init
          @node-click="onNodeClick"
        >
          <Background />
          <Controls />
        </VueFlow>
      </div>

      <!-- Drag handle 1: graph ↔ steps -->
      <div
        v-if="showGraph"
        class="h-1.5 cursor-row-resize flex items-center justify-center shrink-0 group hover:bg-gray-700/50 transition-colors"
        @mousedown="onDragTop"
      >
        <div class="w-12 h-0.5 rounded bg-gray-600 group-hover:bg-gray-400 transition-colors"></div>
      </div>

      <!-- Panel 2: Steps (65%, or fills remaining when log collapsed) -->
      <div class="min-h-0 flex gap-0 overflow-hidden" :style="logExpanded ? { height: (showGraph ? midPercent : (100 - bottomPercent)) + '%' } : { flex: '1 1 0%' }">
        <!-- Aside: step list -->
        <div class="w-56 shrink-0 border-r border-gray-800 overflow-y-auto">
          <template v-for="(item, idx) in orderedSteps" :key="item.step.id">
            <!-- Branch label divider -->
            <div v-if="item.branchLabel" class="flex items-center gap-1.5 py-1 mt-0.5"
              :style="{ paddingLeft: (item.indent * 8 + 4) + 'px', paddingRight: '8px' }">
              <div class="h-px flex-1 bg-gray-700/60"></div>
              <span class="text-[9px] text-gray-500 uppercase tracking-wider font-medium shrink-0">{{ item.branchLabel }}</span>
              <div class="h-px flex-1 bg-gray-700/60"></div>
            </div>
            <!-- Step row -->
            <div
              :ref="(el: any) => { if (el) stepListRefs[item.step.id] = el }"
              @click="selectStep(item.step.id)"
              class="flex items-center gap-2 py-2 pr-3 cursor-pointer border-l-2 transition-colors text-sm"
              :style="{ paddingLeft: (12 + item.indent * 8) + 'px' }"
              :class="[
                selectedStepId === item.step.id
                  ? 'bg-gray-800 border-blue-500 text-gray-50'
                  : item.indent > 0
                    ? 'border-gray-700/40 text-gray-400 hover:bg-gray-800/50 hover:text-gray-200'
                    : 'border-transparent text-gray-400 hover:bg-gray-800/50 hover:text-gray-200',
              ]"
            >
              <!-- Status dot -->
              <span class="w-2 h-2 rounded-full shrink-0" :class="{
                'bg-gray-600': item.step.status === PipelineStatusType.Pending,
                'bg-green-500 animate-pulse': item.step.status === PipelineStatusType.Running,
                'bg-blue-500': item.step.status === PipelineStatusType.Completed,
                'bg-yellow-500': item.step.status === PipelineStatusType.Paused,
                'bg-indigo-500': item.step.status === PipelineStatusType.WaitingForInput,
                'bg-red-500': item.step.status === PipelineStatusType.Failed,
              }"></span>
              <span class="truncate flex-1">{{ item.step.name }}</span>
              <div v-if="item.step.status === PipelineStatusType.Running" class="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin shrink-0"></div>
              <span v-if="item.step.call_cost?.length" class="text-[10px] text-gray-600 shrink-0">${{ stepCost(item.step.call_cost).toFixed(4) }}</span>
            </div>
          </template>
          <!-- Memory nodes in sidebar -->
          <template v-if="run?.pipeline_snapshot?.memories?.length">
            <div class="px-3 py-1.5 text-[10px] text-gray-600 uppercase font-medium border-t border-gray-800 mt-1">Memory</div>
            <div
              v-for="mem in run.pipeline_snapshot.memories"
              :key="mem.id"
              @click="selectStep(mem.id)"
              class="flex items-center gap-2 px-3 py-2 cursor-pointer border-l-2 transition-colors text-sm"
              :class="[
                selectedMemoryId === mem.id
                  ? 'bg-gray-800 border-sky-500 text-gray-50'
                  : 'border-transparent text-gray-400 hover:bg-gray-800/50 hover:text-gray-200',
              ]"
            >
              <span class="w-2 h-2 rounded-full shrink-0" :class="mem.type === 'long_term' ? 'bg-amber-400' : 'bg-sky-400'"></span>
              <span class="truncate flex-1">{{ mem.name }}</span>
              <span class="text-[10px] text-gray-600 shrink-0">
                {{ ((run.memories || []).find((m: any) => m.id === mem.id)?.messages || []).length }} msgs
              </span>
            </div>
          </template>
        </div>

        <!-- Main: selected step detail or memory detail -->
        <div class="flex-1 min-w-0 overflow-y-auto p-4">
          <!-- Memory display panel -->
          <div v-if="selectedMemory">
            <div class="flex items-center gap-3 mb-4">
              <h3 class="text-lg font-semibold text-gray-50">{{ selectedMemory.name }}</h3>
              <span class="text-xs px-2 py-0.5 rounded-full" :class="selectedMemory.type === 'long_term' ? 'bg-amber-900/50 text-amber-300' : 'bg-sky-900/50 text-sky-300'">
                {{ selectedMemory.type === 'long_term' ? 'Long Term' : 'Short Term' }}
              </span>
              <span class="text-xs text-gray-500">{{ selectedMemory.messages?.length || 0 }} messages</span>
            </div>
            <div v-if="!selectedMemory.messages?.length" class="text-sm text-gray-500 italic">
              No messages accumulated yet.
            </div>
            <div v-else class="space-y-2">
              <div
                v-for="(msg, mi) in selectedMemory.messages"
                :key="mi"
                class="rounded-lg p-3 text-sm"
                :class="msg.role === 'user' ? 'bg-blue-900/20 border border-blue-800/30' : 'bg-gray-800 border border-gray-700/30'"
              >
                <div class="flex items-center gap-2 mb-1">
                  <span class="text-[10px] font-medium uppercase" :class="msg.role === 'user' ? 'text-blue-400' : 'text-gray-400'">{{ msg.role }}</span>
                  <span class="text-[10px] text-gray-600">{{ msg.step_name }}</span>
                  <span class="text-[10px] text-gray-700">{{ msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString() : '' }}</span>
                </div>
                <div class="text-gray-300 whitespace-pre-wrap text-xs">{{ msg.content?.substring(0, 1000) }}</div>
              </div>
            </div>
          </div>

          <div v-else-if="!selectedStep" class="flex items-center justify-center h-full text-gray-500 text-sm">
            Select a step to view its details
          </div>

          <template v-else>
            <!-- Step header -->
            <div class="flex items-center gap-3 mb-4">
              <h3 class="text-lg font-semibold text-gray-50">{{ selectedStep.name }}</h3>
              <span class="text-xs px-2 py-0.5 rounded-full" :class="{
                'bg-gray-700 text-gray-400': selectedStep.status === PipelineStatusType.Pending,
                'bg-green-900/50 text-green-400': selectedStep.status === PipelineStatusType.Running,
                'bg-blue-900/50 text-blue-400': selectedStep.status === PipelineStatusType.Completed,
                'bg-yellow-900/50 text-yellow-400': selectedStep.status === PipelineStatusType.Paused,
                'bg-indigo-900/50 text-indigo-400': selectedStep.status === PipelineStatusType.WaitingForInput,
                'bg-red-900/50 text-red-400': selectedStep.status === PipelineStatusType.Failed,
              }">{{ statusLabels[selectedStep.status] }}</span>
              <span v-if="viewedStepData?.call_cost?.length" class="text-xs text-gray-500">
                ${{ stepCost(viewedStepData.call_cost).toFixed(6) }}
              </span>
              <div class="flex-1"></div>
              <button
                v-if="canEditOutput && editingStepId !== selectedStep.id"
                @click.stop="startEditOutput(selectedStep.id, viewedStepData?.outputs?.[0]?.value ?? '')"
                class="text-xs px-3 py-1 rounded bg-gray-700 text-gray-300 hover:bg-yellow-600 hover:text-gray-50 transition-colors"
              >Edit Output</button>
              <button
                v-if="isRunFinished && (selectedStep.status === PipelineStatusType.Completed || selectedStep.status === PipelineStatusType.Failed)"
                @click.stop="rerun(selectedStep.id)"
                class="text-xs px-3 py-1 rounded bg-gray-700 text-gray-300 hover:bg-blue-600 hover:text-gray-50 transition-colors"
              >Rerun from here</button>
            </div>

            <!-- Execution history selector -->
            <div v-if="selectedStep.execution_history?.length" class="mb-3 flex gap-1 flex-wrap items-center">
              <span class="text-xs text-gray-500 mr-1">Executions:</span>
              <button
                v-for="(_, ei) in selectedStep.execution_history"
                :key="ei"
                class="px-2 py-0.5 text-xs rounded-full transition-colors"
                :class="selectedExecution[selectedStep.id] === ei ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'"
                @click="selectedExecution[selectedStep.id] = ei"
              >Run {{ ei + 1 }}</button>
              <button
                class="px-2 py-0.5 text-xs rounded-full transition-colors"
                :class="selectedExecution[selectedStep.id] === undefined || selectedExecution[selectedStep.id] === -1 ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'"
                @click="delete selectedExecution[selectedStep.id]"
              >Run {{ (selectedStep.execution_history?.length ?? 0) + 1 }} (latest)</button>
            </div>

            <!-- Resolved Inputs -->
            <details v-if="viewedStepData?.resolved_inputs?.length" class="mb-3">
                <summary class="text-xs text-gray-500 cursor-pointer hover:text-gray-300 font-semibold uppercase">Resolved Inputs</summary>
                <div class="mt-1 space-y-1">
                    <div v-for="(inp, ii) in viewedStepData.resolved_inputs" :key="ii" class="text-sm bg-gray-800 rounded px-3 py-2">
                        <span class="text-xs text-gray-500 font-semibold uppercase">{{ inp.name }}</span>
                        <pre class="whitespace-pre-wrap font-mono text-xs text-gray-300 mt-1 max-h-[200px] overflow-auto">{{ inp.value }}</pre>
                    </div>
                </div>
            </details>

            <!-- Live iteration progress (shown when step is running with splits) -->
            <div v-if="iterationProgress[selectedStep.id] && selectedStep.status === PipelineStatusType.Running" class="mb-4">
              <div class="text-xs text-gray-500 mb-2 font-semibold uppercase">Split into {{ iterationProgress[selectedStep.id].total }} iterations</div>
              <div class="flex gap-1 mb-3 flex-wrap">
                <button
                  v-for="i in iterationProgress[selectedStep.id].total"
                  :key="i"
                  class="px-2 py-0.5 text-xs rounded-full transition-colors"
                  :class="
                    iterationProgress[selectedStep.id].completed.some(c => c.index === i - 1)
                      ? (liveIterationSelected[selectedStep.id] === i - 1 ? 'bg-blue-600 text-white' : 'bg-blue-600/50 text-blue-200 hover:bg-blue-600')
                      : i - 1 === iterationProgress[selectedStep.id].activeIndex
                        ? 'bg-green-600 text-white animate-pulse'
                        : 'bg-gray-700 text-gray-500'
                  "
                  @click="liveIterationSelected[selectedStep.id] = i - 1"
                >{{ i }}{{ iterationProgress[selectedStep.id].completed.some(c => c.index === i - 1) ? ' ✓' : i - 1 === iterationProgress[selectedStep.id].activeIndex ? ' ●' : '' }}</button>
              </div>
              <!-- Show content for selected live iteration -->
              <template v-if="liveIterationSelected[selectedStep!.id] !== undefined">
                <!-- Completed iteration: show its output -->
                <template v-if="iterationProgress[selectedStep!.id].completed.some(c => c.index === liveIterationSelected[selectedStep!.id])">
                  <div class="text-sm text-gray-300 bg-gray-800 rounded p-3 overflow-auto">
                    <div v-html="renderMd(iterationProgress[selectedStep!.id].completed.find(c => c.index === liveIterationSelected[selectedStep!.id])?.output ?? '')" class="prose prose-sm max-w-none" :class="{ 'prose-invert': theme === 'dark' }"></div>
                  </div>
                </template>
                <!-- Active iteration: show live stream -->
                <template v-else-if="liveIterationSelected[selectedStep!.id] === iterationProgress[selectedStep!.id].activeIndex">
                  <div class="text-sm text-gray-300 bg-gray-800 rounded p-3">
                    <pre class="whitespace-pre-wrap font-mono text-xs">{{ stepStreams[selectedStep!.id + '_iter_' + iterationProgress[selectedStep!.id].activeIndex] || 'Processing...' }}</pre>
                  </div>
                </template>
                <!-- Pending iteration -->
                <template v-else>
                  <div class="text-sm text-gray-500 bg-gray-800 rounded p-3 italic">Waiting...</div>
                </template>
              </template>
            </div>

            <!-- Streaming output (non-iteration) -->
            <div v-else-if="stepStreams[selectedStep.id]" class="mb-4 text-sm text-gray-300 bg-gray-800 rounded p-3">
              <pre class="whitespace-pre-wrap font-mono text-xs">{{ stepStreams[selectedStep.id] }}</pre>
            </div>

            <!-- Ask User questions -->
            <div v-if="askUserQuestions[selectedStep.id]" class="mb-4 bg-indigo-500/10 border border-indigo-500/30 rounded-lg p-4">
              <div class="text-xs text-indigo-400 font-semibold uppercase mb-3">
                Clarification Needed (Round {{ askUserQuestions[selectedStep.id].round }})
              </div>
              <div v-for="q in askUserQuestions[selectedStep.id].questions" :key="q.id" class="mb-4">
                <label class="block text-sm text-gray-200 mb-2">{{ q.text }}</label>
                <div v-if="q.type === 'choice'" class="space-y-1">
                  <label v-for="opt in q.options" :key="opt" class="flex items-center gap-2 cursor-pointer text-sm text-gray-300 hover:text-gray-50">
                    <input type="radio" :name="`${selectedStep.id}_${q.id}`" :value="opt" v-model="askUserAnswers[selectedStep.id][q.id]" class="accent-indigo-500" />
                    <span>{{ opt }}</span>
                  </label>
                </div>
                <textarea v-else v-model="askUserAnswers[selectedStep.id][q.id]" class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 focus:outline-none focus:border-indigo-500" rows="2" placeholder="Type your answer..." />
              </div>
              <button @click="submitAnswers(selectedStep.id)" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 rounded text-sm font-medium transition-colors">
                Submit Answers
              </button>
            </div>

            <!-- File Upload UI -->
            <div v-if="fileUploadRequests[selectedStep.id]" class="mb-4 bg-sky-500/10 border border-sky-500/30 rounded-lg p-4">
              <div class="text-xs text-sky-400 font-semibold uppercase mb-2">File Upload</div>
              <p class="text-sm text-gray-300 mb-3">{{ fileUploadRequests[selectedStep.id].message }}</p>
              <label
                class="block border-2 border-dashed border-gray-600 rounded-lg p-6 text-center cursor-pointer hover:border-sky-500/50 transition-colors"
                @dragover.prevent
                @drop.prevent="onUploadDrop(selectedStep.id, $event)"
              >
                <svg class="w-8 h-8 mx-auto text-gray-500 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" /></svg>
                <div class="text-gray-400 text-sm mb-1">Drag & drop files here or click to browse</div>
                <input type="file" multiple class="hidden" @change="onUploadSelect(selectedStep.id, $event)" />
              </label>
              <div v-if="pendingUploadFiles[selectedStep.id]?.length" class="mt-3 space-y-1">
                <div v-for="(file, fi) in pendingUploadFiles[selectedStep.id]" :key="fi" class="flex items-center gap-2 text-sm text-gray-300 bg-gray-800 rounded px-3 py-1.5">
                  <span class="truncate flex-1">{{ file.name }}</span>
                  <span class="text-xs text-gray-500 shrink-0">{{ formatFileSize(file.size) }}</span>
                  <button @click="removeUploadFile(selectedStep.id, fi)" class="text-red-400 hover:text-red-300 shrink-0">&times;</button>
                </div>
              </div>
              <button
                @click="submitUpload(selectedStep.id)"
                :disabled="!pendingUploadFiles[selectedStep.id]?.length || uploading[selectedStep.id]"
                class="mt-3 px-4 py-2 bg-sky-600 hover:bg-sky-700 disabled:opacity-50 rounded text-sm font-medium transition-colors"
              >
                {{ uploading[selectedStep.id] ? 'Uploading...' : 'Upload & Continue' }}
              </button>
            </div>

            <!-- Completed output -->
            <template v-else-if="viewedStepData?.outputs?.length">
              <!-- Editing mode -->
              <div v-if="editingStepId === selectedStep.id" class="mb-4">
                <div class="text-xs text-yellow-400 font-semibold uppercase mb-2">Editing Step Output</div>
                <textarea
                  v-model="editedOutputValue"
                  class="w-full px-3 py-2 bg-gray-800 border border-yellow-600/50 rounded text-sm text-gray-200 font-mono focus:outline-none focus:border-yellow-500 resize-y"
                  rows="12"
                ></textarea>
                <div class="flex gap-2 mt-2">
                  <button
                    @click="saveEditOutput"
                    :disabled="savingOutput"
                    class="px-4 py-1.5 bg-yellow-600 hover:bg-yellow-700 disabled:opacity-50 rounded text-sm font-medium transition-colors"
                  >{{ savingOutput ? 'Saving...' : 'Save' }}</button>
                  <button
                    @click="cancelEditOutput"
                    class="px-4 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-sm font-medium transition-colors"
                  >Cancel</button>
                </div>
              </div>
              <!-- Split iterations -->
              <template v-else-if="(viewedStepData.split_count ?? 0) > 1 && viewedStepData.iteration_outputs?.length">
                <div class="mb-4">
                  <div class="text-xs text-gray-500 mb-2 font-semibold uppercase">Split into {{ viewedStepData.split_count }} iterations</div>
                  <div class="flex gap-1 mb-2 flex-wrap">
                    <button
                      v-for="i in viewedStepData.split_count"
                      :key="i"
                      class="px-2 py-0.5 text-xs rounded-full transition-colors"
                      :class="(selectedIteration[selectedStep.id] ?? 0) === i - 1 ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'"
                      @click="selectedIteration[selectedStep.id] = i - 1"
                    >{{ i }}</button>
                  </div>
                  <div class="text-xs text-gray-500 mb-1 truncate" :title="viewedStepData.iteration_outputs[selectedIteration[selectedStep.id] ?? 0]?.input">
                    Input: {{ viewedStepData.iteration_outputs[selectedIteration[selectedStep.id] ?? 0]?.input }}
                  </div>
                  <div class="relative text-sm text-gray-300 bg-gray-800 rounded p-3 overflow-auto group/out">
                    <button @click.stop="copyText(viewedStepData.iteration_outputs[selectedIteration[selectedStep.id] ?? 0]?.output ?? '', `${selectedStep.id}-iter-out`)" class="absolute top-2 right-2 p-1 rounded text-gray-500 hover:text-gray-50 hover:bg-gray-700 opacity-0 group-hover/out:opacity-100 transition-opacity" title="Copy output">
                      <svg v-if="copiedKey === `${selectedStep.id}-iter-out`" class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                      <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" stroke-width="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke-width="2"/></svg>
                    </button>
                    <div v-html="renderMd(viewedStepData.iteration_outputs[selectedIteration[selectedStep.id] ?? 0]?.output ?? '')" class="prose prose-sm max-w-none" :class="{ 'prose-invert': theme === 'dark' }"></div>
                  </div>
                  <details v-if="viewedStepData.iteration_outputs[selectedIteration[selectedStep.id] ?? 0]?.agent_output" class="mt-2">
                    <summary class="text-xs text-gray-500 cursor-pointer hover:text-gray-300 font-semibold uppercase">Agent Response</summary>
                    <div class="relative mt-1 text-sm text-gray-300 bg-gray-800 rounded p-3 overflow-auto group/agent">
                      <button @click.stop="copyText(viewedStepData.iteration_outputs[selectedIteration[selectedStep.id] ?? 0]?.agent_output ?? '', `${selectedStep.id}-iter-agent`)" class="absolute top-2 right-2 p-1 rounded text-gray-500 hover:text-gray-50 hover:bg-gray-700 opacity-0 group-hover/agent:opacity-100 transition-opacity" title="Copy agent output">
                        <svg v-if="copiedKey === `${selectedStep.id}-iter-agent`" class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                        <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" stroke-width="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke-width="2"/></svg>
                      </button>
                      <div v-html="renderMd(viewedStepData.iteration_outputs[selectedIteration[selectedStep.id] ?? 0]?.agent_output ?? '')" class="prose prose-sm max-w-none" :class="{ 'prose-invert': theme === 'dark' }"></div>
                    </div>
                  </details>
                </div>
              </template>
              <!-- Start step or multi-input: show each output labeled -->
              <template v-else-if="selectedStep.is_start && viewedStepData!.outputs.length > 1">
                <div v-for="(out, oi) in viewedStepData!.outputs" :key="oi" class="relative mb-3 text-sm text-gray-300 bg-gray-800 rounded p-3 group/out">
                  <button @click.stop="copyText(out.value ?? '', `${selectedStep.id}-start-${oi}`)" class="absolute top-2 right-2 p-1 rounded text-gray-500 hover:text-gray-50 hover:bg-gray-700 opacity-0 group-hover/out:opacity-100 transition-opacity" title="Copy output">
                    <svg v-if="copiedKey === `${selectedStep.id}-start-${oi}`" class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                    <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" stroke-width="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke-width="2"/></svg>
                  </button>
                  <div class="text-xs text-gray-500 mb-1 font-semibold uppercase">{{ out.name }}</div>
                  <div v-html="renderMd(String(out.value ?? ''))" class="prose prose-sm max-w-none" :class="{ 'prose-invert': theme === 'dark' }"></div>
                </div>
              </template>
              <!-- Normal step output -->
              <template v-else>
                <!-- Multiple outputs: Agent Response shown, Tool Result collapsed -->
                <template v-if="viewedStepData!.outputs.length > 1">
                  <div class="relative mb-3 text-sm text-gray-300 bg-gray-800 rounded p-3 overflow-auto group/agent">
                    <button @click.stop="copyText(viewedStepData!.outputs[1]?.value ?? '', `${selectedStep.id}-agent`)" class="absolute top-2 right-2 p-1 rounded text-gray-500 hover:text-gray-50 hover:bg-gray-700 opacity-0 group-hover/agent:opacity-100 transition-opacity" title="Copy agent output">
                      <svg v-if="copiedKey === `${selectedStep.id}-agent`" class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                      <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" stroke-width="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke-width="2"/></svg>
                    </button>
                    <div class="text-xs text-gray-500 mb-1 font-semibold uppercase">Agent Response</div>
                    <div v-html="renderMd(String(viewedStepData!.outputs[1]?.value ?? ''), selectedStep.id)" class="prose prose-sm max-w-none" :class="{ 'prose-invert': theme === 'dark' }"></div>
                  </div>
                  <details class="mb-3">
                    <summary class="text-xs text-gray-500 cursor-pointer hover:text-gray-300 font-semibold uppercase">Tool Result</summary>
                    <div class="relative mt-1 text-sm text-gray-300 bg-gray-800 rounded p-3 overflow-auto group/out">
                      <button @click.stop="copyText(viewedStepData!.outputs[0]?.value ?? '', `${selectedStep.id}-out`)" class="absolute top-2 right-2 p-1 rounded text-gray-500 hover:text-gray-50 hover:bg-gray-700 opacity-0 group-hover/out:opacity-100 transition-opacity" title="Copy output">
                        <svg v-if="copiedKey === `${selectedStep.id}-out`" class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                        <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" stroke-width="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke-width="2"/></svg>
                      </button>
                      <div v-html="renderMarkdownToolResult(String(viewedStepData!.outputs[0]?.value ?? ''))" class="prose prose-sm max-w-none" :class="{ 'prose-invert': theme === 'dark' }"></div>
                    </div>
                  </details>
                </template>
                <!-- Single output: show openly without label -->
                <template v-else>
                  <div class="relative mb-3 text-sm text-gray-300 bg-gray-800 rounded p-3 overflow-auto group/out">
                    <button @click.stop="copyText(viewedStepData!.outputs[0]?.value ?? '', `${selectedStep.id}-out`)" class="absolute top-2 right-2 p-1 rounded text-gray-500 hover:text-gray-50 hover:bg-gray-700 opacity-0 group-hover/out:opacity-100 transition-opacity" title="Copy output">
                      <svg v-if="copiedKey === `${selectedStep.id}-out`" class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                      <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" stroke-width="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke-width="2"/></svg>
                    </button>
                    <div v-html="renderMd(String(viewedStepData!.outputs[0]?.value ?? ''), selectedStep.id)" class="prose prose-sm max-w-none" :class="{ 'prose-invert': theme === 'dark' }"></div>
                  </div>
                </template>
              </template>
            </template>

            <!-- Error / status text (green for If=true, red otherwise) -->
            <div
              v-if="viewedStepData?.status_text"
              class="mb-3 text-sm rounded p-3"
              :class="selectedStep?.tool?.type === ToolType.If && viewedStepData.outputs?.[0]?.value === 'true'
                ? 'text-green-400 bg-green-900/20'
                : 'text-red-400 bg-red-900/20'"
            >{{ viewedStepData.status_text }}</div>

            <!-- Token details -->
            <div v-if="viewedStepData?.call_cost?.length" class="mb-3 text-xs text-gray-500">
              <template v-if="(viewedStepData.split_count ?? 0) > 1 && viewedStepData.iteration_outputs?.length">
                <div v-for="(iter, ii) in viewedStepData.iteration_outputs" :key="ii">
                  <template v-if="iter.cost?.length">
                    <span class="text-gray-600">Iter {{ ii + 1 }}: </span>
                    <span v-for="(c, ci) in iter.cost" :key="ci" class="mr-3">
                      {{ c.model }}: {{ c.input_token_count }} in / {{ c.output_token_count }} out
                    </span>
                  </template>
                </div>
              </template>
              <template v-else>
                <span v-for="(c, idx) in viewedStepData.call_cost" :key="idx" class="mr-3">
                  <span v-if="c.detail === 'validation'" class="text-green-500/70">[validation] </span>{{ c.model }}: {{ c.input_token_count }} in / {{ c.output_token_count }} out
                </span>
              </template>
            </div>

            <!-- Prompt used -->
            <details v-if="viewedStepData?.prompt_used" class="mb-3">
              <summary class="text-xs text-gray-500 cursor-pointer hover:text-gray-300 font-semibold uppercase">Prompt Sent</summary>
              <div class="mt-1 space-y-2">
                <div v-if="viewedStepData.prompt_used.system" class="relative text-sm text-gray-300 bg-gray-800 rounded p-3 overflow-auto max-h-[40vh] group/sys">
                  <button @click.stop="copyText(viewedStepData.prompt_used.system, `${selectedStep.id}-sys`)" class="absolute top-2 right-2 p-1 rounded text-gray-500 hover:text-gray-50 hover:bg-gray-700 opacity-0 group-hover/sys:opacity-100 transition-opacity" title="Copy system prompt">
                    <svg v-if="copiedKey === `${selectedStep.id}-sys`" class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                    <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" stroke-width="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke-width="2"/></svg>
                  </button>
                  <div class="text-xs text-gray-500 mb-1 font-semibold uppercase">System Prompt</div>
                  <pre class="whitespace-pre-wrap font-mono text-xs">{{ viewedStepData.prompt_used.system }}</pre>
                </div>
                <div v-if="viewedStepData.prompt_used.user" class="relative text-sm text-gray-300 bg-gray-800 rounded p-3 overflow-auto max-h-[40vh] group/usr">
                  <button @click.stop="copyText(viewedStepData.prompt_used.user, `${selectedStep.id}-usr`)" class="absolute top-2 right-2 p-1 rounded text-gray-500 hover:text-gray-50 hover:bg-gray-700 opacity-0 group-hover/usr:opacity-100 transition-opacity" title="Copy user prompt">
                    <svg v-if="copiedKey === `${selectedStep.id}-usr`" class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                    <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" stroke-width="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke-width="2"/></svg>
                  </button>
                  <div class="text-xs text-gray-500 mb-1 font-semibold uppercase">User Prompt</div>
                  <pre class="whitespace-pre-wrap font-mono text-xs">{{ viewedStepData.prompt_used.user }}</pre>
                </div>
              </div>
            </details>
          </template>
        </div>
      </div>

      <!-- Drag handle 2: steps ↔ log (only when log expanded) -->
      <div
        v-if="logExpanded"
        class="h-1.5 cursor-row-resize flex items-center justify-center shrink-0 group hover:bg-gray-700/50 transition-colors"
        @mousedown="onDragBottom"
      >
        <div class="w-12 h-0.5 rounded bg-gray-600 group-hover:bg-gray-400 transition-colors"></div>
      </div>

      <!-- Panel 3: Execution Log (15% when expanded, 28px header-only when collapsed) -->
      <div
        class="shrink-0 overflow-hidden"
        :style="logExpanded ? { height: bottomPercent + '%', minHeight: '0px' } : { height: '28px' }"
      >
        <RunLogViewer :run-id="id" :steps="run.steps" :initial-entries="run.log_entries" v-model:expanded="logExpanded" class="h-full" />
      </div>
    </div>
  </div>
</template>
