<script setup lang="ts">
import type { Model } from '@/models'

defineProps<{
  model: Partial<Model>
  isNew: boolean
}>()

const emit = defineEmits<{
  save: []
  cancel: []
}>()
</script>

<template>
  <div class="bg-gray-850 border border-blue-500/50 rounded-lg">
    <div class="px-5 py-3 border-b border-gray-800 flex items-center justify-between">
      <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">
        {{ isNew ? 'Add Model' : 'Edit Model' }}
      </h2>
      <button @click="emit('cancel')" class="p-1 text-gray-400 hover:text-gray-200 transition-colors" title="Cancel">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
      </button>
    </div>
    <div class="p-5 space-y-4">
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="block text-xs text-gray-500 mb-1">Model ID</label>
          <input
            v-model="model.model_id"
            placeholder="e.g. claude-opus-4-6"
            class="input-base"
          />
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1">Display Name</label>
          <input
            v-model="model.name"
            placeholder="e.g. Claude Opus 4.6"
            class="input-base"
          />
        </div>
      </div>
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="block text-xs text-gray-500 mb-1">Input Cost ($/M tokens)</label>
          <input
            v-model.number="model.input_cost"
            type="number"
            step="0.01"
            class="input-base"
          />
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1">Output Cost ($/M tokens)</label>
          <input
            v-model.number="model.output_cost"
            type="number"
            step="0.01"
            class="input-base"
          />
        </div>
      </div>
      <div class="flex gap-2 pt-2">
        <button @click="emit('save')" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors">
          Save
        </button>
        <button @click="emit('cancel')" class="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition-colors">
          Cancel
        </button>
      </div>
    </div>
  </div>
</template>
