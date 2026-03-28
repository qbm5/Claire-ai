<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import type { AiPipelineMemory } from '@/models'

const props = defineProps<{
  data: AiPipelineMemory
  selected?: boolean
}>()

const mem = computed(() => props.data)
const isLongTerm = computed(() => mem.value.type === 'long_term')

const colors = computed(() => isLongTerm.value
  ? { border: 'border-amber-400', bg: 'bg-amber-500/10', text: 'text-amber-400', badge: 'bg-amber-900/50 text-amber-300', handle: '!bg-amber-400 !border-amber-600' }
  : { border: 'border-sky-400', bg: 'bg-sky-500/10', text: 'text-sky-400', badge: 'bg-sky-900/50 text-sky-300', handle: '!bg-sky-400 !border-sky-600' }
)

const msgCount = computed(() => mem.value.messages?.length ?? 0)
</script>

<template>
  <div
    class="rounded-2xl border-2 border-dashed shadow-lg min-w-[160px] px-4 py-3 cursor-pointer"
    :class="[colors.border, colors.bg, { 'ring-2 ring-blue-400': selected }]"
  >
    <div class="flex items-center gap-2 mb-1">
      <svg class="w-4 h-4 shrink-0" :class="colors.text" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
          d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
      </svg>
      <span class="font-medium text-gray-50 text-sm truncate">{{ mem.name }}</span>
    </div>
    <div class="flex items-center gap-2">
      <span class="text-[10px] px-1.5 py-0.5 rounded-full" :class="colors.badge">
        {{ isLongTerm ? 'Long Term' : 'Short Term' }}
      </span>
      <span v-if="msgCount > 0" class="text-[10px] text-gray-400">{{ msgCount }} msgs</span>
    </div>

    <!-- Bottom handle: steps connect TO this memory -->
    <Handle
      type="target"
      :id="mem.id + '_target'"
      :position="Position.Bottom"
      class="!w-3 !h-3 !border-2" :class="colors.handle"
    />
  </div>
</template>
