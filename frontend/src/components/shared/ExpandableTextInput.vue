<script setup lang="ts">
import { ref } from 'vue'
import TemplateInput from './TemplateInput.vue'

defineProps<{
  modelValue: string
  placeholder?: string
  label?: string
  variables?: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const expanded = ref(false)

function onInput(e: Event) {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}
</script>

<template>
  <!-- Inline: real editable input with expand button -->
  <div class="flex items-center gap-0.5 w-full">
    <TemplateInput
      v-if="variables?.length"
      :modelValue="modelValue"
      @update:modelValue="emit('update:modelValue', $event)"
      :variables="variables"
      mode="textarea"
      :placeholder="placeholder"
      :rows="1"
      inputClass="w-full px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500 resize-none overflow-hidden whitespace-nowrap"
      class="flex-1 min-w-0"
    />
    <textarea
      v-else
      :value="modelValue"
      @input="onInput"
      :placeholder="placeholder"
      rows="1"
      class="flex-1 min-w-0 px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500 resize-none overflow-hidden whitespace-nowrap"
    />
    <button
      @click="expanded = true"
      type="button"
      title="Expand editor"
      class="shrink-0 p-1 text-gray-500 hover:text-gray-300 transition-colors"
    >
      <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
      </svg>
    </button>
  </div>

  <!-- Expanded: modal with textarea -->
  <Teleport to="body">
    <div v-if="expanded" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" @click.self="expanded = false">
      <div class="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-lg p-5 space-y-3">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-gray-200">{{ label || 'Edit Value' }}</h3>
          <button @click="expanded = false" class="text-gray-500 hover:text-gray-300 text-lg leading-none">&times;</button>
        </div>
        <TemplateInput
          v-if="variables?.length"
          :modelValue="modelValue"
          @update:modelValue="emit('update:modelValue', $event)"
          :variables="variables"
          mode="textarea"
          :placeholder="placeholder"
          :rows="10"
          inputClass="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm font-mono focus:outline-none focus:border-blue-500 resize-y"
        />
        <textarea
          v-else
          :value="modelValue"
          @input="onInput"
          :placeholder="placeholder"
          rows="10"
          class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm font-mono focus:outline-none focus:border-blue-500 resize-y"
          autofocus
        />
        <div class="flex justify-end">
          <button @click="expanded = false" class="px-4 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-xs transition-colors">
            Done
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
