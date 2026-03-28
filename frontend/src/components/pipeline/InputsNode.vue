<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { PropertyType, type AiPipeline } from '@/models'

const typeLabels: Record<number, string> = {
  [PropertyType.TEXT]: 'Text',
  [PropertyType.NUMBER]: 'Num',
  [PropertyType.BOOLEAN]: 'Bool',
  [PropertyType.DATE]: 'Date',
  [PropertyType.PASSWORD]: 'Pass',
  [PropertyType.SELECT]: 'List',
}

const props = defineProps<{
  data: {
    pipeline: AiPipeline
  }
}>()

const pipeline = computed(() => props.data.pipeline)
</script>

<template>
  <div class="rounded-lg border-2 border-emerald-500 bg-emerald-500/10 px-4 py-3 min-w-[160px] shadow-lg">
    <div class="font-medium text-emerald-400 text-sm mb-2">Pipeline Inputs</div>
    <div v-for="inp in pipeline.inputs" :key="inp.name" class="text-xs text-gray-300 truncate">
      {{ inp.name }}
      <span v-if="inp.type != null && inp.type !== PropertyType.TEXT" class="text-gray-500 text-[10px]">({{ typeLabels[inp.type] || 'Text' }})</span>
      <span v-if="inp.value" class="text-gray-500">= {{ inp.value }}</span>
    </div>
    <Handle type="source" :position="Position.Bottom" class="!w-3 !h-3 !bg-emerald-400 !border-2 !border-emerald-600" />
  </div>
</template>
