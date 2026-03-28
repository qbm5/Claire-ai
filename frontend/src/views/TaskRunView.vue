<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getTaskRun } from '@/services/taskService'
import type { TaskRun, TaskPlanStep } from '@/models'
import { useToast } from '@/composables/useToast'

const { show: toast } = useToast()
const router = useRouter()
const props = defineProps<{ id: string }>()

const run = ref<TaskRun | null>(null)
const loading = ref(true)
const expandedSteps = ref<Set<string>>(new Set())

onMounted(async () => {
  try {
    run.value = await getTaskRun(props.id)
    // Auto-expand completed and failed steps
    for (const step of (run.value.plan || [])) {
      if (step.status === 'completed' || step.status === 'failed') {
        expandedSteps.value.add(step.id)
      }
    }
  } catch {
    toast('Task run not found', 'error')
    router.push('/dashboard')
    return
  }
  loading.value = false
})

function toggleStep(id: string) {
  if (expandedSteps.value.has(id)) expandedSteps.value.delete(id)
  else expandedSteps.value.add(id)
}

const statusLabel: Record<number, string> = {
  0: 'Pending', 1: 'Running', 2: 'Completed', 3: 'Failed', 4: 'Waiting',
}
const statusBadge: Record<number, string> = {
  0: 'bg-gray-700 text-gray-300',
  1: 'bg-blue-900/60 text-blue-400',
  2: 'bg-green-900/60 text-green-400',
  3: 'bg-red-900/60 text-red-400',
  4: 'bg-indigo-900/60 text-indigo-400',
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

function formatDate(iso: string | undefined): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString()
}

const totalCost = computed(() => {
  if (!run.value?.total_cost) return null
  const tc = run.value.total_cost
  if (typeof tc === 'object' && tc.total_cost > 0) return tc
  return null
})

function goBack() {
  if (run.value?.task_plan_id) {
    router.push(`/task/${run.value.task_plan_id}`)
  } else {
    router.push('/dashboard')
  }
}
</script>

<template>
  <div class="flex h-full">
    <!-- Left Sidebar -->
    <div class="w-72 bg-gray-900 border-r border-gray-800 flex flex-col">
      <!-- Header -->
      <div class="p-4 border-b border-gray-800">
        <div class="flex items-center gap-3">
          <button @click="goBack" class="text-gray-400 hover:text-gray-50 text-sm">&larr;</button>
          <h1 class="text-lg font-bold truncate">Task Run</h1>
          <span class="px-1.5 py-0.5 text-[9px] font-semibold rounded bg-amber-900/40 text-amber-400 border border-amber-800/60 leading-none shrink-0">BETA</span>
        </div>
      </div>

      <!-- Sidebar content -->
      <div class="flex-1 overflow-y-auto min-h-0">
        <div v-if="loading" class="p-4 text-gray-400 text-sm">Loading...</div>

        <template v-else-if="run">
          <!-- Run Info -->
          <div class="p-4 border-b border-gray-800 space-y-3">
            <div class="text-xs text-gray-500 uppercase font-medium">Run Details</div>

            <div>
              <label class="block text-xs text-gray-500 mb-0.5">Status</label>
              <span class="text-xs px-2 py-0.5 rounded" :class="statusBadge[run.status] || statusBadge[0]">
                {{ statusLabel[run.status] || 'Unknown' }}
              </span>
            </div>

            <div>
              <label class="block text-xs text-gray-500 mb-0.5">Model</label>
              <span class="text-sm text-gray-300">{{ run.model || 'Default' }}</span>
            </div>

            <div>
              <label class="block text-xs text-gray-500 mb-0.5">Created</label>
              <span class="text-sm text-gray-300">{{ formatDate(run.created_at) }}</span>
            </div>

            <div v-if="run.updated_at">
              <label class="block text-xs text-gray-500 mb-0.5">Updated</label>
              <span class="text-sm text-gray-300">{{ formatDate(run.updated_at) }}</span>
            </div>

            <div>
              <label class="block text-xs text-gray-500 mb-0.5">Steps</label>
              <span class="text-sm text-gray-300">{{ run.plan?.length || 0 }} steps</span>
            </div>
          </div>

          <!-- Cost Summary -->
          <div v-if="totalCost" class="p-4 border-b border-gray-800 space-y-2">
            <div class="text-xs text-gray-500 uppercase font-medium">Cost Summary</div>
            <div class="space-y-1">
              <div class="flex justify-between text-xs">
                <span class="text-gray-500">Input tokens</span>
                <span class="text-gray-300">{{ totalCost.input_tokens?.toLocaleString() || 0 }}</span>
              </div>
              <div class="flex justify-between text-xs">
                <span class="text-gray-500">Output tokens</span>
                <span class="text-gray-300">{{ totalCost.output_tokens?.toLocaleString() || 0 }}</span>
              </div>
              <div class="flex justify-between text-xs font-medium pt-1 border-t border-gray-800">
                <span class="text-gray-400">Total</span>
                <span class="text-gray-200">{{ formatCost(totalCost.total_cost) }}</span>
              </div>
            </div>
          </div>

          <!-- Input Values -->
          <div v-if="run.input_values && Object.keys(run.input_values).length" class="p-4">
            <div class="text-xs text-gray-500 uppercase font-medium mb-2">Input Values</div>
            <div class="space-y-1">
              <div v-for="(val, key) in run.input_values" :key="key" class="text-xs">
                <span class="text-gray-500">{{ key }}:</span>
                <span class="text-gray-300 ml-1 break-all">{{ val }}</span>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- Actions -->
      <div v-if="!loading && run?.task_plan_id" class="p-3 border-t border-gray-800">
        <button
          @click="router.push(`/task/${run.task_plan_id}`)"
          class="w-full px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition-colors"
        >
          Open Task Plan
        </button>
      </div>
    </div>

    <!-- Main Content -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <div v-if="loading" class="flex-1 flex items-center justify-center text-gray-400">Loading...</div>

      <div v-else-if="run" class="flex-1 overflow-y-auto">
        <div class="max-w-4xl mx-auto px-6 py-6 space-y-5">

          <!-- Request -->
          <div>
            <label class="block text-xs text-gray-500 uppercase font-medium mb-2">Request</label>
            <div class="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-300 whitespace-pre-wrap">{{ run.request || '(no request)' }}</div>
          </div>

          <!-- Plan Steps -->
          <div v-if="run.plan?.length" class="space-y-2">
            <h3 class="text-xs text-gray-500 uppercase tracking-wider font-medium">Execution Steps</h3>

            <div v-for="(step, idx) in run.plan" :key="step.id" class="relative">
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
                    <svg v-else-if="step.status === 'running'" class="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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

                  <!-- Expand arrow -->
                  <svg class="w-4 h-4 text-gray-500 ml-auto shrink-0 transition-transform" :class="{ 'rotate-180': expandedSteps.has(step.id) }" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
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
                  <div class="text-xs text-gray-500 mb-1 mt-2">Instructions</div>
                  <div class="text-sm text-gray-400 mb-2 whitespace-pre-wrap">{{ step.instructions }}</div>
                  <div v-if="step.output" class="mt-2">
                    <div class="text-xs text-gray-500 mb-1">Output</div>
                    <pre class="text-sm text-gray-300 bg-gray-950 rounded-lg p-3 overflow-auto max-h-64 whitespace-pre-wrap font-mono">{{ step.output }}</pre>
                  </div>
                  <div v-if="step.cost" class="mt-2 text-[11px] text-gray-500">
                    {{ step.cost.input_tokens.toLocaleString() }} in / {{ step.cost.output_tokens.toLocaleString() }} out · {{ formatCost(step.cost.total_cost) }}
                  </div>
                </div>
              </div>
            </div>

            <!-- Total cost summary -->
            <div v-if="totalCost && totalCost.total_cost > 0" class="flex items-center justify-end gap-4 pt-2 text-xs text-gray-400 border-t border-gray-800/50">
              <span>{{ totalCost.input_tokens?.toLocaleString() || 0 }} input tokens</span>
              <span>{{ totalCost.output_tokens?.toLocaleString() || 0 }} output tokens</span>
              <span class="font-medium text-gray-300">Total: {{ formatCost(totalCost.total_cost) }}</span>
            </div>
          </div>

          <!-- Final Output -->
          <div v-if="run.output" class="space-y-2">
            <h3 class="text-xs text-gray-500 uppercase tracking-wider font-medium">Final Output</h3>
            <pre class="text-sm text-gray-300 bg-gray-950 rounded-lg p-4 overflow-auto max-h-96 whitespace-pre-wrap font-mono border border-gray-800">{{ run.output }}</pre>
          </div>

        </div>
      </div>
    </div>
  </div>
</template>
