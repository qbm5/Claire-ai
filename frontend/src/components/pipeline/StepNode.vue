<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { ToolType, PipelineStatusType, type AiPipelineStep } from '@/models'

const props = defineProps<{
  data: AiPipelineStep
  selected?: boolean
}>()

const emit = defineEmits<{
  (e: 'select', step: AiPipelineStep): void
}>()

const step = computed(() => props.data)
const toolType = computed(() => step.value.tool?.type ?? ToolType.LLM)
const isIf = computed(() => toolType.value === ToolType.If)
const isEnd = computed(() => toolType.value === ToolType.End)
const isStart = computed(() => toolType.value === ToolType.Start)

const typeColors: Record<number, { border: string; bg: string; label: string }> = {
  [ToolType.LLM]:      { border: 'border-purple-500', bg: 'bg-purple-500/10', label: 'LLM' },
  [ToolType.Endpoint]:  { border: 'border-green-500',  bg: 'bg-green-500/10',  label: 'Endpoint' },
  [ToolType.Pause]:     { border: 'border-yellow-500', bg: 'bg-yellow-500/10', label: 'Pause' },
  [ToolType.Agent]:     { border: 'border-orange-500', bg: 'bg-orange-500/10', label: 'Agent' },
  [ToolType.Pipeline]:  { border: 'border-blue-500',   bg: 'bg-blue-500/10',   label: 'Pipeline' },
  [ToolType.If]:        { border: 'border-cyan-500',   bg: 'bg-cyan-500/10',   label: 'If' },
  [ToolType.Parallel]:  { border: 'border-pink-500',   bg: 'bg-pink-500/10',   label: 'Parallel' },
  [ToolType.End]:       { border: 'border-red-500',    bg: 'bg-red-500/10',    label: 'End' },
  [ToolType.Wait]:      { border: 'border-amber-500',  bg: 'bg-amber-500/10',  label: 'Wait' },
  [ToolType.Start]:     { border: 'border-emerald-500', bg: 'bg-emerald-500/10', label: 'Start' },
  [ToolType.LoopCounter]: { border: 'border-teal-500', bg: 'bg-teal-500/10', label: 'Loop Counter' },
  [ToolType.AskUser]:     { border: 'border-indigo-500', bg: 'bg-indigo-500/10', label: 'Ask User' },
  [ToolType.FileUpload]:  { border: 'border-sky-500',    bg: 'bg-sky-500/10',    label: 'File Upload' },
  [ToolType.ClaudeCode]:  { border: 'border-cyan-500',   bg: 'bg-cyan-500/10',   label: 'Claude Code' },
}

const colors = computed(() => typeColors[toolType.value] || typeColors[ToolType.LLM])

const statusBorder = computed(() => {
  switch (step.value.status) {
    case PipelineStatusType.Running: return 'border-green-500'
    case PipelineStatusType.Completed: return 'border-blue-500'
    case PipelineStatusType.Failed: return 'border-red-500'
    case PipelineStatusType.Paused: return 'border-yellow-500'
    case PipelineStatusType.WaitingForInput: return 'border-indigo-500'
    default: return 'border-gray-600'  // Pending
  }
})

const statusDot: Record<number, string> = {
  [PipelineStatusType.Pending]: 'bg-gray-500',
  [PipelineStatusType.Running]: 'bg-blue-500 animate-pulse',
  [PipelineStatusType.Completed]: 'bg-green-500',
  [PipelineStatusType.Failed]: 'bg-red-500',
  [PipelineStatusType.Paused]: 'bg-yellow-500',
  [PipelineStatusType.WaitingForInput]: 'bg-indigo-500 animate-pulse',
}

// Input count indicators
const inputCount = computed(() => step.value.tool?.request_inputs?.length ?? 0)
</script>

<template>
  <div
    class="rounded-lg border-2 shadow-lg min-w-[180px] cursor-pointer"
    :class="[statusBorder, colors.bg, { 'ring-2 ring-blue-400': selected }]"
  >
    <!-- Memory handle: top (source, connects up to memory nodes) -->
    <Handle
      type="source"
      :id="step.id + '_memory'"
      :position="Position.Top"
      class="!w-3 !h-3 !bg-sky-400 !border-2 !border-sky-600"
    />

    <!-- Target handle: everything except Start -->
    <Handle
      v-if="!isStart"
      type="target"
      :id="step.id + '_target'"
      :position="Position.Left"
      class="!w-3 !h-3 !bg-gray-400 !border-2 !border-gray-600"
    />

    <!-- Start node -->
    <div v-if="isStart" class="px-4 py-3 text-center">
      <div class="text-emerald-400 font-bold text-sm">Start</div>
    </div>

    <!-- End node -->
    <div v-else-if="isEnd" class="px-4 py-3 text-center">
      <div class="flex items-center gap-2">
        <div class="w-2 h-2 rounded-full" :class="statusDot[step.status]"></div>
        <span class="font-medium text-gray-50 text-sm">{{ step.name }}</span>
      </div>
      <div class="text-xs text-red-400 mt-1">End</div>
    </div>

    <!-- If node -->
    <div v-else-if="isIf" class="px-4 py-3">
      <div class="flex items-center gap-2 mb-1">
        <div class="w-2 h-2 rounded-full" :class="statusDot[step.status]"></div>
        <span class="font-medium text-gray-50 text-sm">{{ step.name }}</span>
      </div>
      <div class="text-xs text-cyan-400 mb-2">If Condition</div>
      <div class="flex justify-between text-[10px] px-1">
        <span class="text-green-400">True</span>
        <span class="text-red-400">False</span>
      </div>
      <div class="text-[10px] text-center text-gray-500 mt-1">After</div>
    </div>

    <!-- Normal step (LLM, Endpoint, Agent, Pipeline, etc.) -->
    <div v-else class="px-4 py-3">
      <div class="flex items-center gap-2 mb-1">
        <div class="w-2 h-2 rounded-full shrink-0" :class="statusDot[step.status]"></div>
        <span class="font-medium text-gray-50 text-sm truncate">{{ step.name }}</span>
        <span v-if="(step.split_count ?? 0) > 1" class="text-[10px] text-gray-400 font-mono">&times;{{ step.split_count }}</span>
      </div>
      <div class="flex items-center gap-2">
        <img v-if="step.tool?.image_url" :src="step.tool.image_url" class="w-7 h-7 rounded object-cover shrink-0 border border-gray-600 bg-black" />
        <div class="text-xs text-gray-400 truncate">
          {{ step.tool?.name || 'No tool' }}
          <span class="text-gray-600 ml-1">({{ colors.label }})</span>
        </div>
      </div>
      <!-- Input indicators -->
      <div v-if="inputCount > 0" class="flex gap-0.5 mt-2">
        <div
          v-for="i in inputCount"
          :key="i"
          class="h-0.5 flex-1 rounded bg-gray-500"
          :title="step.tool?.request_inputs?.[i-1]?.name"
        ></div>
      </div>
    </div>

    <!-- Source handles -->

    <!-- Start: single output bottom -->
    <Handle
      v-if="isStart"
      type="source"
      :id="step.id + '_source'"
      :position="Position.Right"
      class="!w-3 !h-3 !bg-emerald-400 !border-2 !border-emerald-600"
    />

    <!-- Normal step (not If, not End, not Start): single output right -->
    <Handle
      v-if="!isIf && !isEnd && !isStart"
      type="source"
      :id="step.id + '_source'"
      :position="Position.Right"
      class="!w-3 !h-3 !bg-blue-400 !border-2 !border-blue-600"
    />

    <!-- If node: True, False, After handles on the right side -->
    <template v-if="isIf">
      <Handle
        type="source"
        :id="step.id + '_true'"
        :position="Position.Right"
        :style="{ top: '30%' }"
        class="!w-3 !h-3 !bg-green-400 !border-2 !border-green-600"
      />
      <Handle
        type="source"
        :id="step.id + '_false'"
        :position="Position.Right"
        :style="{ top: '55%' }"
        class="!w-3 !h-3 !bg-red-400 !border-2 !border-red-600"
      />
      <Handle
        type="source"
        :id="step.id + '_after'"
        :position="Position.Bottom"
        class="!w-3 !h-3 !bg-gray-400 !border-2 !border-gray-500"
      />
    </template>

    <!-- End node: no output handles -->

    <!-- Disabled overlay -->
    <div v-if="step.disabled" class="absolute inset-0 bg-gray-900/60 rounded-lg flex items-center justify-center">
      <span class="text-xs text-gray-400">Disabled</span>
    </div>
  </div>
</template>
