<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { onEvent } from '@/services/eventBus'
import type { RunLogEntry, AiPipelineStep } from '@/models'

const props = defineProps<{
  runId: string
  steps: AiPipelineStep[]
  expanded: boolean
  initialEntries?: RunLogEntry[]
}>()

const emit = defineEmits<{
  (e: 'update:expanded', value: boolean): void
}>()

const entries = ref<RunLogEntry[]>([])
const seenTimestamps = new Set<string>()

// Seed from persisted entries
watch(() => props.initialEntries, (init) => {
  if (init?.length && entries.value.length === 0) {
    entries.value = [...init]
    for (const e of init) {
      seenTimestamps.add(e.timestamp + e.message)
    }
  }
}, { immediate: true })
const autoScroll = ref(true)
const logContainer = ref<HTMLElement | null>(null)

const MAX_ENTRIES = 500

const sourceColors: Record<string, string> = {
  pipeline: 'text-gray-400',
  llm: 'text-purple-400',
  agent: 'text-orange-400',
  tool: 'text-green-400',
  endpoint: 'text-teal-400',
  condition: 'text-cyan-400',
}

const levelColors: Record<string, string> = {
  error: 'text-red-400',
  warn: 'text-amber-400',
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 })
  } catch {
    return ts
  }
}

function stepName(stepId?: string): string {
  if (!stepId) return ''
  const step = props.steps.find(s => s.id === stepId)
  return step?.name || ''
}

function scrollToBottom() {
  if (autoScroll.value && logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
}

function onScroll() {
  if (!logContainer.value) return
  const { scrollTop, scrollHeight, clientHeight } = logContainer.value
  // Re-enable auto-scroll when user scrolls to within 20px of bottom
  autoScroll.value = scrollHeight - scrollTop - clientHeight < 20
}

function clear() {
  entries.value = []
}

let cleanup: (() => void) | null = null

onMounted(() => {
  cleanup = onEvent('run_log', (data: any) => {
    if (data.run_id !== props.runId) return
    const entry: RunLogEntry = {
      run_id: data.run_id,
      step_id: data.step_id,
      timestamp: data.timestamp,
      level: data.level || 'info',
      source: data.source || 'pipeline',
      message: data.message || '',
      detail: data.detail,
    }
    const key = entry.timestamp + entry.message
    if (seenTimestamps.has(key)) return
    seenTimestamps.add(key)
    entries.value.push(entry)
    if (entries.value.length > MAX_ENTRIES) {
      entries.value = entries.value.slice(-MAX_ENTRIES)
    }
    nextTick(scrollToBottom)
  })
})

onUnmounted(() => {
  cleanup?.()
})
</script>

<template>
  <div class="border-t border-gray-800 bg-gray-950 flex flex-col overflow-hidden">
    <!-- Header bar -->
    <div
      class="flex items-center gap-2 px-3 h-7 shrink-0 cursor-pointer select-none hover:bg-gray-900 transition-colors"
      @click="emit('update:expanded', !expanded)"
    >
      <svg
        class="w-3 h-3 text-gray-500 transition-transform"
        :class="{ 'rotate-90': expanded }"
        fill="none" stroke="currentColor" viewBox="0 0 24 24"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
      </svg>
      <span class="text-xs font-semibold text-gray-500 uppercase tracking-wide">Execution Log</span>
      <span v-if="entries.length" class="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-gray-700 text-gray-300 min-w-[1.25rem] text-center">{{ entries.length }}</span>
      <div class="flex-1"></div>
      <button
        v-if="entries.length"
        @click.stop="clear"
        class="text-[10px] text-gray-600 hover:text-gray-400 px-1"
        title="Clear log"
      >Clear</button>
      <button
        @click.stop="autoScroll = !autoScroll"
        class="text-[10px] px-1 rounded"
        :class="autoScroll ? 'text-blue-400' : 'text-gray-600 hover:text-gray-400'"
        :title="autoScroll ? 'Auto-scroll ON' : 'Auto-scroll OFF'"
      >
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
        </svg>
      </button>
    </div>

    <!-- Log content -->
    <div
      v-show="expanded"
      ref="logContainer"
      class="flex-1 min-h-0 overflow-y-auto overflow-x-hidden font-mono text-[11px] leading-relaxed px-3 pb-2"
      @scroll="onScroll"
    >
      <div v-if="!entries.length" class="text-gray-700 py-2 text-center">
        Waiting for log events...
      </div>
      <div
        v-for="(entry, i) in entries"
        :key="i"
        class="flex gap-2 py-px hover:bg-gray-900/50"
      >
        <span class="text-gray-600 shrink-0 w-20">{{ formatTime(entry.timestamp) }}</span>
        <span
          class="shrink-0 w-16 text-right"
          :class="levelColors[entry.level] || sourceColors[entry.source] || 'text-gray-400'"
        >{{ entry.source }}</span>
        <span
          v-if="stepName(entry.step_id)"
          class="text-gray-600 shrink-0"
        >[{{ stepName(entry.step_id) }}]</span>
        <span :class="levelColors[entry.level] || 'text-gray-300'">{{ entry.message }}</span>
      </div>
    </div>
  </div>
</template>
