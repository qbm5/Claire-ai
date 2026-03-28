<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { getTaskPlan, saveTaskPlan, getTaskRuns, deleteTaskRun } from '@/services/taskService'
import { wsTaskExecute, type TaskExecuteEvent, type StepCost, type TotalCost } from '@/services/taskService'
import { createTaskPlan, type TaskPlan, type TaskPlanStep, type TaskRun, PropertyType } from '@/models'
import { useModels, loadModels } from '@/composables/useModels'
import ModelSelectDropdown from '@/components/shared/ModelSelectDropdown.vue'
import TemplateInput from '@/components/shared/TemplateInput.vue'
import { useToast } from '@/composables/useToast'

const { show: toast } = useToast()
const router = useRouter()
const route = useRoute()
const { models } = useModels()

const taskPlan = ref<TaskPlan>(createTaskPlan())
const isNew = ref(false)
const isQuickRun = ref(false)
const loading = ref(true)
const dirty = ref(false)

// Execution state
const executing = ref(false)
const executionStatus = ref('')
const planSteps = ref<TaskPlanStep[]>([])
const expandedSteps = ref<Set<string>>(new Set())
const abortFn = ref<(() => void) | null>(null)
const sendAnswerFn = ref<((stepId: string, answers: { id: string; answer: string }[]) => void) | null>(null)
const approveFn = ref<(() => void) | null>(null)
const skipStepFn = ref<((stepId: string) => void) | null>(null)
const unskipStepFn = ref<((stepId: string) => void) | null>(null)
const setStepModelFn = ref<((stepId: string, model: string) => void) | null>(null)

// Ask user state
const askUserStepId = ref('')
const askUserQuestions = ref<{ id: string; text: string; type?: string; options?: string[] }[]>([])
const askUserAnswers = ref<Record<string, string>>({})

// Cost tracking
const planningCost = ref<StepCost | null>(null)
const totalCost = ref<TotalCost | null>(null)

// Approval state (manual mode)
const awaitingApproval = ref(false)

// Active processes
const activeProcesses = ref<{ pid: number; command: string; running: boolean }[]>([])

// Timing
const runStartTime = ref<number>(0)
const runElapsed = ref<number>(0)
const runFinishedAt = ref<string>('')
let elapsedTimer: ReturnType<typeof setInterval> | null = null

// Input form state
const showInputForm = ref(false)
const inputFormValues = ref<Record<string, string>>({})

// Run history
const runs = ref<TaskRun[]>([])
const showHistory = ref(false)

// Quick-run request input
const quickRequest = ref('')
const requestText = computed({
  get: () => isQuickRun.value || isNew.value ? quickRequest.value : taskPlan.value.request,
  set: (v: string) => {
    if (isQuickRun.value || isNew.value) quickRequest.value = v
    else taskPlan.value.request = v
    dirty.value = true
  },
})

// Template variables from inputs
const templateVars = computed(() =>
  taskPlan.value.inputs.filter(i => i.name.trim()).map(i => i.name)
)

const planId = computed(() => route.params.id as string)

onMounted(async () => {
  await loadModels()
  const id = planId.value
  if (id === 'new') {
    isNew.value = true
    isQuickRun.value = route.query.quick === '1'
    loading.value = false
    return
  }
  try {
    taskPlan.value = await getTaskPlan(id)
    // Migration for older plans missing auto_run
    if (taskPlan.value.auto_run === undefined) taskPlan.value.auto_run = true
    runs.value = await getTaskRuns(id)
  } catch {
    toast('Task not found', 'error')
    router.push('/tasks')
    return
  }
  loading.value = false
})

onUnmounted(() => {
  if (elapsedTimer) clearInterval(elapsedTimer)
})

function addInput() {
  taskPlan.value.inputs.push({ name: '', value: '', type: PropertyType.TEXT, is_required: false })
  dirty.value = true
}

function removeInput(idx: number) {
  taskPlan.value.inputs.splice(idx, 1)
  dirty.value = true
}

async function save() {
  if (!taskPlan.value.name.trim()) {
    toast('Name is required', 'error')
    return
  }
  try {
    await saveTaskPlan(taskPlan.value)
    toast('Saved', 'success')
    dirty.value = false
    if (isNew.value) {
      isNew.value = false
      router.replace(`/task/${taskPlan.value.id}`)
    }
  } catch (e: any) {
    toast(e.message || 'Save failed', 'error')
  }
}

function toggleStep(id: string) {
  if (expandedSteps.value.has(id)) expandedSteps.value.delete(id)
  else expandedSteps.value.add(id)
}

// ── Execution ─────────────────────────────────────────────────────

function handleEvent(event: TaskExecuteEvent) {
  if (event.type === 'status') {
    executionStatus.value = event.text || ''
  } else if (event.type === 'plan') {
    planSteps.value = (event.plan?.steps || []).map(s => ({ ...s, status: s.status || 'pending', output: '' }))
    if (event.planning_cost) {
      planningCost.value = event.planning_cost
    }
    executionStatus.value = taskPlan.value.auto_run ? 'Executing...' : 'Review plan...'
  } else if (event.type === 'awaiting_approval') {
    awaitingApproval.value = true
    executionStatus.value = 'Waiting for approval...'
  } else if (event.type === 'step_skipped') {
    const step = planSteps.value.find(s => s.id === event.step_id)
    if (step) step.status = 'skipped'
  } else if (event.type === 'step_unskipped') {
    const step = planSteps.value.find(s => s.id === event.step_id)
    if (step) step.status = 'pending'
  } else if (event.type === 'step_start') {
    const step = planSteps.value.find(s => s.id === event.step_id)
    if (step) {
      step.status = 'running'
      if (event.model) step.model = event.model
    }
    awaitingApproval.value = false
    // Start elapsed timer on first step
    if (!runStartTime.value) {
      runStartTime.value = Date.now()
      runElapsed.value = 0
      elapsedTimer = setInterval(() => { runElapsed.value = Math.round((Date.now() - runStartTime.value) / 1000) }, 1000)
    }
  } else if (event.type === 'step_delta') {
    const step = planSteps.value.find(s => s.id === event.step_id)
    if (step) step.output = (step.output || '') + (event.text || '')
  } else if (event.type === 'step_complete') {
    const step = planSteps.value.find(s => s.id === event.step_id)
    if (step) {
      step.status = 'completed'
      if (event.output && !step.output) step.output = event.output
      if (event.cost) step.cost = event.cost
      if (event.duration_s != null) step.duration_s = event.duration_s
      if (event.model) step.model = event.model
      expandedSteps.value.add(step.id)
    }
  } else if (event.type === 'step_error') {
    const step = planSteps.value.find(s => s.id === event.step_id)
    if (step) {
      step.status = 'failed'
      step.output = event.error || 'Unknown error'
    }
  } else if (event.type === 'step_tool_call') {
    const step = planSteps.value.find(s => s.id === event.step_id)
    if (step) step.output = (step.output || '') + `\n[Calling ${event.name}...]`
  } else if (event.type === 'step_tool_result') {
    const step = planSteps.value.find(s => s.id === event.step_id)
    if (step) step.output = (step.output || '') + `\n[${event.name} returned: ${(event.result || '').substring(0, 200)}]\n`
  } else if (event.type === 'ask_user') {
    askUserStepId.value = event.step_id || ''
    askUserQuestions.value = event.questions || []
    askUserAnswers.value = {}
    for (const q of askUserQuestions.value) {
      askUserAnswers.value[q.id] = q.type === 'choice' && q.options?.length ? q.options[0] : ''
    }
    executionStatus.value = 'Waiting for your input...'
  } else if (event.type === 'processes') {
    activeProcesses.value = (event.processes || []).filter((p: any) => p.running)
  } else if (event.type === 'complete') {
    executing.value = false
    executionStatus.value = 'Complete'
    activeProcesses.value = []
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
    runFinishedAt.value = new Date().toLocaleTimeString()
    if (event.total_cost) totalCost.value = event.total_cost
    if (planSteps.value.length) expandedSteps.value.add(planSteps.value[planSteps.value.length - 1].id)
  } else if (event.type === 'error') {
    executing.value = false
    executionStatus.value = ''
    activeProcesses.value = []
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
    toast(event.text || 'Execution failed', 'error')
  }
}

function execute() {
  const request = requestText.value
  if (!request.trim() && !taskPlan.value.plan.length) {
    toast('Enter a request', 'error')
    return
  }

  // If inputs are defined, show the input form first
  const inputs = taskPlan.value.inputs.filter(i => i.name.trim())
  if (inputs.length > 0 && !showInputForm.value) {
    inputFormValues.value = {}
    for (const inp of inputs) {
      inputFormValues.value[inp.name] = inp.value || ''
    }
    showInputForm.value = true
    return
  }

  showInputForm.value = false
  doExecute()
}

function submitInputForm() {
  for (const inp of taskPlan.value.inputs) {
    if (inp.is_required && inp.name.trim() && !inputFormValues.value[inp.name]?.trim()) {
      toast(`"${inp.name}" is required`, 'error')
      return
    }
  }
  showInputForm.value = false
  doExecute()
}

function cancelInputForm() {
  showInputForm.value = false
}

async function doExecute() {
  const request = requestText.value

  executing.value = true
  executionStatus.value = 'Connecting...'
  planSteps.value = []
  expandedSteps.value.clear()
  askUserStepId.value = ''
  planningCost.value = null
  totalCost.value = null
  awaitingApproval.value = false
  runStartTime.value = 0
  runElapsed.value = 0
  runFinishedAt.value = ''
  if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }

  // Build input values
  const inputValues: Record<string, any> = {}
  const inputs = taskPlan.value.inputs.filter(i => i.name.trim())
  if (inputs.length > 0) {
    for (const inp of inputs) {
      inputValues[inp.name] = inputFormValues.value[inp.name] || inp.value || ''
    }
  }

  const savedPlan = taskPlan.value.plan.length > 0 ? taskPlan.value.plan : null
  const autoRun = taskPlan.value.auto_run

  const { promise, abort, sendAnswer, approve, skipStep, unskipStep, setStepModel } = wsTaskExecute(
    request,
    taskPlan.value.model,
    isNew.value ? '' : taskPlan.value.id,
    inputValues,
    savedPlan,
    autoRun,
    handleEvent,
  )
  abortFn.value = abort
  sendAnswerFn.value = sendAnswer
  approveFn.value = approve
  skipStepFn.value = skipStep
  unskipStepFn.value = unskipStep
  setStepModelFn.value = setStepModel

  try {
    await promise
  } catch {
    if (executing.value) {
      executing.value = false
      executionStatus.value = ''
      toast('Connection failed', 'error')
    }
  }
}

function approveAndRun() {
  if (approveFn.value) approveFn.value()
  awaitingApproval.value = false
  executionStatus.value = 'Executing...'
}

function toggleSkipStep(step: TaskPlanStep) {
  if (step.status === 'skipped') {
    if (unskipStepFn.value) unskipStepFn.value(step.id)
  } else {
    if (skipStepFn.value) skipStepFn.value(step.id)
  }
}

function submitAnswers() {
  if (!sendAnswerFn.value || !askUserStepId.value) return
  const answers = askUserQuestions.value.map(q => ({
    id: q.id,
    answer: askUserAnswers.value[q.id] || '',
  }))
  sendAnswerFn.value(askUserStepId.value, answers)
  askUserStepId.value = ''
  executionStatus.value = 'Continuing execution...'
}

function stopExecution() {
  if (abortFn.value) abortFn.value()
  executing.value = false
  executionStatus.value = 'Stopped'
  activeProcesses.value = []
  if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
  // Mark any running steps as failed/stopped
  for (const step of planSteps.value) {
    if (step.status === 'running') {
      step.status = 'failed'
      step.output = (step.output || '') + '\n[Stopped by user]'
    }
  }
}

async function saveAsPlan() {
  if (!planSteps.value.length) return
  const cleanSteps = planSteps.value.map(s => ({
    id: s.id,
    name: s.name,
    type: s.type,
    tool_id: s.tool_id,
    tool_name: s.tool_name,
    tool_image: s.tool_image,
    tool_inputs: s.tool_inputs,
    output_format: s.output_format,
    instructions: s.instructions,
    questions: s.questions,
  }))
  taskPlan.value.plan = cleanSteps as TaskPlanStep[]
  if (!taskPlan.value.request) {
    taskPlan.value.request = quickRequest.value || ''
  }
  if (!taskPlan.value.name) {
    taskPlan.value.name = quickRequest.value.substring(0, 60) || 'Untitled Task'
  }
  try {
    await saveTaskPlan(taskPlan.value)
    toast('Saved as reusable task', 'success')
    isNew.value = false
    isQuickRun.value = false
    router.replace(`/task/${taskPlan.value.id}`)
  } catch (e: any) {
    toast(e.message || 'Save failed', 'error')
  }
}

async function deleteRun(run: TaskRun) {
  await deleteTaskRun(run.id)
  runs.value = runs.value.filter(r => r.id !== run.id)
}

async function remove() {
  if (!confirm(`Delete "${taskPlan.value.name || 'Untitled'}"?`)) return
  const { deleteTaskPlan } = await import('@/services/taskService')
  await deleteTaskPlan(taskPlan.value.id)
  router.push('/tasks')
}

const stepTypeLabel = (type: string) => {
  switch (type) {
    case 'reasoning': return 'LLM'
    case 'tool': return 'Tool'
    case 'ask_user': return 'User Input'
    default: return type
  }
}

const stepTypeColor = (type: string) => {
  switch (type) {
    case 'reasoning': return 'bg-purple-600/20 text-purple-400'
    case 'tool': return 'bg-blue-600/20 text-blue-400'
    case 'ask_user': return 'bg-amber-600/20 text-amber-400'
    default: return 'bg-gray-600/20 text-gray-400'
  }
}

function formatCost(cost: number): string {
  return `$${cost.toFixed(4)}`
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}m ${s}s`
}

function handleStepModelChange(step: TaskPlanStep, model: string) {
  step.model = model
  if (setStepModelFn.value) setStepModelFn.value(step.id, model)
}

// Running cost total from completed steps
const runningCost = computed(() => {
  let total = planningCost.value?.total_cost || 0
  for (const s of planSteps.value) {
    if (s.cost) total += s.cost.total_cost
  }
  return total
})
</script>

<template>
  <div class="flex h-full">
    <!-- Left Sidebar -->
    <div class="w-72 bg-gray-900 border-r border-gray-800 flex flex-col">
      <!-- Header -->
      <div class="p-4 border-b border-gray-800">
        <div class="flex items-center gap-3">
          <button @click="router.push('/tasks')" class="text-gray-400 hover:text-gray-50 text-sm">&larr;</button>
          <h1 class="text-lg font-bold truncate">
            {{ isQuickRun ? 'Quick Run' : (isNew ? 'New Task' : (taskPlan.name || 'Edit Task')) }}
          </h1>
          <span class="px-1.5 py-0.5 text-[9px] font-semibold rounded bg-amber-900/40 text-amber-400 border border-amber-800/60 leading-none shrink-0">BETA</span>
        </div>
      </div>

      <!-- Scrollable sidebar content -->
      <div class="flex-1 overflow-y-auto min-h-0">
        <div v-if="loading" class="p-4 text-gray-400 text-sm">Loading...</div>

        <template v-else>
          <!-- Settings -->
          <div class="p-4 border-b border-gray-800 space-y-3">
            <div class="text-xs text-gray-500 uppercase font-medium">Settings</div>

            <div v-if="!isQuickRun">
              <label class="block text-xs text-gray-400 mb-1">Name</label>
              <input v-model="taskPlan.name" placeholder="Task name" class="input-sm" @input="dirty = true" />
            </div>

            <div>
              <label class="block text-xs text-gray-400 mb-1">Model</label>
              <ModelSelectDropdown v-model="taskPlan.model" :models="models" />
            </div>

            <div v-if="!isQuickRun">
              <label class="block text-xs text-gray-400 mb-1">Description</label>
              <input v-model="taskPlan.description" placeholder="Short summary for list" class="input-sm" @input="dirty = true" />
              <p class="text-[10px] text-gray-600 mt-0.5">Display only — not sent to AI.</p>
            </div>

            <div v-if="!isQuickRun">
              <label class="block text-xs text-gray-400 mb-1">Tag</label>
              <input v-model="taskPlan.tag" placeholder="Optional tag" class="input-sm" @input="dirty = true" />
            </div>

            <div class="flex items-center gap-2">
              <label class="text-xs text-gray-400">Auto Run</label>
              <input type="checkbox" v-model="taskPlan.auto_run" class="accent-purple-500" @change="dirty = true" />
              <span class="text-[10px] text-gray-600">{{ taskPlan.auto_run ? 'Execute immediately after planning' : 'Review & approve plan first' }}</span>
            </div>
          </div>

          <!-- Inputs -->
          <div class="p-4 border-b border-gray-800">
            <div class="flex items-center justify-between mb-2">
              <div class="text-xs text-gray-500 uppercase font-medium">Inputs</div>
              <button @click="addInput" class="text-xs text-blue-400 hover:text-blue-300">+ Add</button>
            </div>
            <p class="text-[10px] text-gray-600 mb-2">Variables filled before each run. Use <code class="text-gray-500" v-pre>{{name}}</code> in request.</p>
            <div class="space-y-2">
              <div v-for="(inp, idx) in taskPlan.inputs" :key="idx" class="p-2 bg-gray-800/50 rounded border border-gray-800 space-y-1">
                <div class="flex items-center gap-1">
                  <input v-model="inp.name" placeholder="Name" class="flex-1 px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" @input="dirty = true" />
                  <label class="text-[10px] text-gray-500 flex items-center gap-0.5">
                    <input type="checkbox" v-model="inp.is_required" class="accent-blue-500" @change="dirty = true" /> Req
                  </label>
                  <button @click="removeInput(idx)" class="text-red-400 hover:text-red-300 text-xs">&times;</button>
                </div>
                <input v-model="inp.value" placeholder="Default value" class="w-full px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" @input="dirty = true" />
              </div>
            </div>
          </div>

          <!-- History (saved plans only) -->
          <div v-if="!isQuickRun && !isNew && runs.length" class="p-4">
            <button @click="showHistory = !showHistory" class="text-xs text-gray-500 uppercase font-medium hover:text-gray-300 w-full text-left">
              Run History ({{ runs.length }}) {{ showHistory ? '▾' : '▸' }}
            </button>
            <div v-if="showHistory" class="mt-2 space-y-1">
              <div
                v-for="run in runs"
                :key="run.id"
                class="flex items-center gap-2 py-1.5 px-2 bg-gray-800/50 rounded text-xs hover:bg-gray-800 transition-colors cursor-pointer"
                @click="router.push(`/task-run/${run.id}`)"
              >
                <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="{
                  'bg-green-400': run.status === 2,
                  'bg-red-400': run.status === 3,
                  'bg-yellow-400': run.status === 1,
                  'bg-gray-500': run.status === 0,
                }"></span>
                <span class="text-gray-400 truncate flex-1">{{ run.request?.substring(0, 40) || 'No request' }}</span>
                <span class="text-gray-600">{{ run.plan?.length || 0 }}s</span>
                <button @click.stop="deleteRun(run)" class="text-red-400/60 hover:text-red-400">&times;</button>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- Actions -->
      <div v-if="!loading" class="p-3 border-t border-gray-800 space-y-2">
        <button
          v-if="!isQuickRun"
          @click="save"
          :disabled="!taskPlan.name.trim()"
          class="w-full px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
        >
          Save
        </button>
        <button
          v-if="!isQuickRun && !isNew"
          @click="remove"
          class="w-full px-3 py-2 bg-red-900/40 hover:bg-red-900/60 text-red-400 rounded-lg text-sm font-medium transition-colors"
        >
          Delete
        </button>
      </div>
    </div>

    <!-- Main Content -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <div v-if="loading" class="flex-1 flex items-center justify-center text-gray-400">Loading...</div>

      <div v-else class="flex-1 overflow-y-auto">
        <div class="max-w-4xl mx-auto px-6 py-6 space-y-5">

          <!-- Request -->
          <div>
            <label class="block text-xs text-gray-500 uppercase font-medium mb-2">Request</label>
            <TemplateInput
              v-model="requestText"
              :variables="templateVars"
              mode="textarea"
              :rows="4"
              placeholder="Describe what you want the AI to accomplish..."
              input-class="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-blue-500 resize-y"
            />
            <p v-if="templateVars.length" class="text-[11px] text-gray-600 mt-1">
              Type <code class="text-gray-500" v-pre>{{</code> to autocomplete input variables.
            </p>
          </div>

          <!-- Execute Button Row -->
          <div class="flex items-center gap-3">
            <button
              v-if="!executing"
              @click="execute"
              :disabled="!requestText.trim() && !taskPlan.plan.length"
              class="px-6 py-2.5 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition-colors"
            >
              Execute
            </button>
            <button
              v-else
              @click="stopExecution"
              class="px-6 py-2.5 bg-red-600 hover:bg-red-700 rounded-lg text-sm font-medium transition-colors"
            >
              Stop
            </button>

            <span v-if="executionStatus" class="text-sm text-gray-400">
              <template v-if="executing && !awaitingApproval">
                <svg class="w-4 h-4 animate-spin inline mr-1" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
              </template>
              <svg v-else-if="executionStatus === 'Complete'" class="w-4 h-4 inline mr-1 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
              {{ executionStatus }}
            </span>

            <!-- Elapsed time -->
            <span v-if="runElapsed > 0" class="text-xs text-gray-500">
              {{ formatDuration(runElapsed) }}
            </span>
            <span v-if="runFinishedAt" class="text-xs text-gray-600">
              finished {{ runFinishedAt }}
            </span>

            <!-- Running cost -->
            <span v-if="runningCost > 0" class="text-xs text-gray-500 ml-auto">
              Cost: {{ formatCost(runningCost) }}
            </span>

            <button
              v-if="!executing && planSteps.length > 0 && (isQuickRun || isNew)"
              @click="saveAsPlan"
              class="ml-auto px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm transition-colors"
            >
              Save as Reusable Task
            </button>
          </div>

          <!-- Input Form (pre-execution) -->
          <div v-if="showInputForm" class="bg-blue-900/20 border border-blue-700/50 rounded-xl p-5 space-y-4">
            <div class="flex items-center gap-2 text-blue-400 text-sm font-medium">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
              Fill in inputs before running
            </div>
            <div v-for="inp in taskPlan.inputs.filter(i => i.name.trim())" :key="inp.name" class="space-y-1.5">
              <label class="block text-sm text-gray-200">
                {{ inp.name }}
                <span v-if="inp.is_required" class="text-red-400 text-xs ml-1">*</span>
              </label>
              <textarea
                v-model="inputFormValues[inp.name]"
                rows="2"
                class="input-base resize-y"
                :placeholder="inp.value || 'Enter value...'"
              ></textarea>
            </div>
            <div class="flex gap-2">
              <button @click="submitInputForm" class="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-medium transition-colors">
                Run
              </button>
              <button @click="cancelInputForm" class="px-4 py-2 text-gray-400 hover:text-gray-200 text-sm transition-colors">
                Cancel
              </button>
            </div>
          </div>

          <!-- Approval bar (manual mode) -->
          <div v-if="awaitingApproval && planSteps.length" class="bg-purple-900/20 border border-purple-700/50 rounded-xl p-4">
            <div class="flex items-center gap-3">
              <div class="flex-1">
                <div class="text-sm font-medium text-purple-300">Review plan before running</div>
                <p class="text-xs text-gray-400 mt-0.5">Toggle steps to skip, then approve to begin execution.</p>
              </div>
              <button @click="approveAndRun" class="px-5 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-medium transition-colors">
                Approve & Run
              </button>
            </div>
          </div>

          <!-- Active Processes -->
          <div v-if="activeProcesses.length" class="bg-orange-900/20 border border-orange-700/50 rounded-xl p-4">
            <div class="flex items-center gap-2 mb-2">
              <svg class="w-4 h-4 text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
              <span class="text-sm font-medium text-orange-300">Active Processes</span>
              <span class="text-xs px-1.5 py-0.5 bg-orange-900/60 text-orange-400 rounded-full">{{ activeProcesses.length }}</span>
            </div>
            <div class="space-y-1">
              <div v-for="proc in activeProcesses" :key="proc.pid" class="flex items-center gap-3 px-3 py-1.5 bg-gray-900/50 rounded text-xs">
                <span class="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0"></span>
                <span class="text-gray-500 font-mono shrink-0">PID {{ proc.pid }}</span>
                <span class="text-gray-400 font-mono truncate">{{ proc.command }}</span>
              </div>
            </div>
          </div>

          <!-- Ask User UI -->
          <div v-if="askUserStepId" class="bg-amber-900/20 border border-amber-700/50 rounded-xl p-5 space-y-4">
            <div class="flex items-center gap-2 text-amber-400 text-sm font-medium">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              Input Required
            </div>
            <div v-for="q in askUserQuestions" :key="q.id" class="space-y-1.5">
              <label class="block text-sm text-gray-200">{{ q.text }}</label>
              <select v-if="q.type === 'choice' && q.options?.length" v-model="askUserAnswers[q.id]" class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-amber-500">
                <option v-for="opt in q.options" :key="opt" :value="opt">{{ opt }}</option>
              </select>
              <input v-else v-model="askUserAnswers[q.id]" type="text" class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-amber-500" placeholder="Your answer..." />
            </div>
            <button @click="submitAnswers" class="px-4 py-2 bg-amber-600 hover:bg-amber-700 rounded-lg text-sm font-medium transition-colors">
              Submit Answers
            </button>
          </div>

          <!-- Plan Steps -->
          <div v-if="planSteps.length" class="space-y-2">
            <div class="flex items-center justify-between">
              <h3 class="text-xs text-gray-500 uppercase tracking-wider font-medium">Execution Plan</h3>
              <div v-if="planningCost" class="text-[11px] text-gray-500">
                Planning: {{ planningCost.input_tokens.toLocaleString() }} in / {{ planningCost.output_tokens.toLocaleString() }} out · {{ formatCost(planningCost.total_cost) }}
              </div>
            </div>

            <div v-for="(step, idx) in planSteps" :key="step.id" class="relative">
              <!-- Connector line -->
              <div v-if="idx > 0" class="absolute left-4 -top-2 w-px h-2 bg-gray-700"></div>

              <div
                class="border rounded-lg transition-colors"
                :class="{
                  'border-gray-700 bg-gray-900/50': step.status === 'pending',
                  'border-purple-600/50 bg-purple-900/10': step.status === 'running',
                  'border-green-700/50 bg-green-900/10': step.status === 'completed',
                  'border-red-700/50 bg-red-900/10': step.status === 'failed',
                  'border-gray-700/50 bg-gray-900/30 opacity-50': step.status === 'skipped',
                }"
              >
                <div
                  class="flex items-center gap-3 px-4 py-3 cursor-pointer"
                  @click="toggleStep(step.id)"
                >
                  <!-- Status icon -->
                  <div class="w-6 h-6 flex items-center justify-center shrink-0">
                    <svg v-if="step.status === 'completed'" class="w-5 h-5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
                    <svg v-else-if="step.status === 'running'" class="w-5 h-5 text-purple-400 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <svg v-else-if="step.status === 'failed'" class="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                    <svg v-else-if="step.status === 'skipped'" class="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7" /></svg>
                    <div v-else class="w-3 h-3 rounded-full border-2 border-gray-600"></div>
                  </div>

                  <!-- Step info -->
                  <span class="text-xs text-gray-500 shrink-0">{{ idx + 1 }}.</span>
                  <span class="font-medium text-sm text-gray-200 truncate" :class="{ 'line-through': step.status === 'skipped' }">{{ step.name }}</span>
                  <span class="text-xs px-2 py-0.5 rounded-full font-medium shrink-0" :class="stepTypeColor(step.type)">
                    {{ stepTypeLabel(step.type) }}
                  </span>
                  <span v-if="step.tool_name" class="flex items-center gap-1.5 shrink-0 min-w-0">
                    <img v-if="step.tool_image" :src="step.tool_image" class="w-4 h-4 rounded object-cover shrink-0" />
                    <span class="text-xs text-gray-500 truncate">{{ step.tool_name }}</span>
                  </span>

                  <!-- Model badge -->
                  <span v-if="step.model || step.tool_model" class="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-500 shrink-0 truncate max-w-[140px]" :title="step.model || step.tool_model">
                    {{ step.model || step.tool_model }}
                  </span>

                  <!-- Step cost -->
                  <span v-if="step.cost" class="text-[10px] text-gray-500 shrink-0">{{ formatCost(step.cost.total_cost) }}</span>

                  <!-- Skip toggle (when awaiting approval) -->
                  <button
                    v-if="awaitingApproval && step.status !== 'running'"
                    @click.stop="toggleSkipStep(step)"
                    class="text-xs px-2 py-0.5 rounded transition-colors shrink-0 ml-auto"
                    :class="step.status === 'skipped'
                      ? 'bg-gray-700 text-gray-400 hover:text-gray-200'
                      : 'text-gray-500 hover:bg-red-900/30 hover:text-red-400'"
                  >
                    {{ step.status === 'skipped' ? 'Unskip' : 'Skip' }}
                  </button>

                  <!-- Expand arrow -->
                  <svg v-if="!awaitingApproval" class="w-4 h-4 text-gray-500 ml-auto shrink-0 transition-transform" :class="{ 'rotate-180': expandedSteps.has(step.id) }" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
                </div>

                <!-- Expanded content -->
                <div v-if="expandedSteps.has(step.id)" class="px-4 pb-3 pt-0 border-t border-gray-800/50">
                  <div v-if="step.tool_inputs && Object.keys(step.tool_inputs).length" class="my-2">
                    <div class="text-xs text-gray-500 mb-1">Tool Inputs</div>
                    <div v-for="(val, key) in step.tool_inputs" :key="key" class="flex gap-2 text-xs mb-0.5">
                      <span class="text-gray-500 shrink-0">{{ key }}:</span>
                      <span class="text-blue-400 break-all">{{ val }}</span>
                    </div>
                  </div>
                  <div v-if="step.output_format && step.output_format !== 'raw'" class="my-2">
                    <span class="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">{{ step.output_format }}</span>
                  </div>
                  <div class="text-xs text-gray-500 mb-1 mt-2">Instructions</div>
                  <div class="text-sm text-gray-400 mb-2 whitespace-pre-wrap">{{ step.instructions }}</div>
                  <div v-if="step.output" class="mt-2">
                    <div class="text-xs text-gray-500 mb-1">Output</div>
                    <pre class="text-sm text-gray-300 bg-gray-950 rounded-lg p-3 overflow-auto max-h-64 whitespace-pre-wrap font-mono">{{ step.output }}</pre>
                  </div>
                  <div v-if="step.cost || step.duration_s != null || step.model" class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-500">
                    <span v-if="step.model">{{ step.model }}</span>
                    <span v-if="step.duration_s != null">{{ formatDuration(step.duration_s) }}</span>
                    <span v-if="step.cost">{{ step.cost.input_tokens.toLocaleString() }} in / {{ step.cost.output_tokens.toLocaleString() }} out · {{ formatCost(step.cost.total_cost) }}</span>
                  </div>

                  <!-- Per-step model override (approval mode) -->
                  <div v-if="awaitingApproval && step.status === 'pending'" class="mt-2">
                    <label class="text-[10px] text-gray-500 mb-1 block">Model</label>
                    <ModelSelectDropdown
                      :modelValue="step.model || taskPlan.model"
                      @update:modelValue="(m: string) => handleStepModelChange(step, m)"
                      :models="models"
                      class="w-full"
                    />
                  </div>
                </div>
              </div>
            </div>

            <!-- Total cost summary -->
            <div v-if="totalCost && totalCost.total_cost > 0" class="flex items-center justify-end gap-4 pt-2 text-xs text-gray-400 border-t border-gray-800/50">
              <span>{{ totalCost.input_tokens.toLocaleString() }} input tokens</span>
              <span>{{ totalCost.output_tokens.toLocaleString() }} output tokens</span>
              <span class="font-medium text-gray-300">Total: {{ formatCost(totalCost.total_cost) }}</span>
            </div>
          </div>

          <!-- Saved plan steps (when not executing) -->
          <div v-else-if="taskPlan.plan.length && !executing" class="space-y-2">
            <h3 class="text-xs text-gray-500 uppercase tracking-wider font-medium">Saved Plan ({{ taskPlan.plan.length }} steps)</h3>
            <div v-for="(step, idx) in taskPlan.plan" :key="step.id" class="flex items-center gap-3 px-4 py-2.5 bg-gray-900/50 border border-gray-800 rounded-lg">
              <span class="text-xs text-gray-500">{{ idx + 1 }}.</span>
              <span class="text-sm text-gray-200 truncate">{{ step.name }}</span>
              <span class="text-xs px-2 py-0.5 rounded-full font-medium shrink-0" :class="stepTypeColor(step.type)">
                {{ stepTypeLabel(step.type) }}
              </span>
              <span v-if="step.tool_name" class="flex items-center gap-1.5 shrink-0">
                <img v-if="step.tool_image" :src="step.tool_image" class="w-4 h-4 rounded object-cover" />
                <span class="text-xs text-gray-500">{{ step.tool_name }}</span>
              </span>
              <span v-if="step.model || step.tool_model" class="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-500 shrink-0 truncate max-w-[140px]" :title="step.model || step.tool_model">
                {{ step.model || step.tool_model }}
              </span>
            </div>
          </div>

        </div>
      </div>
    </div>
  </div>
</template>
