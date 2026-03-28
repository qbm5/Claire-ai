<script setup lang="ts">
import { ref, watch } from 'vue'
import { PropertyType } from '@/models'

const props = defineProps<{
  modelValue: boolean
  input: { name: string; type?: PropertyType; is_required?: boolean; data?: any } | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const typeLabels: { value: PropertyType; label: string }[] = [
  { value: PropertyType.TEXT, label: 'Text' },
  { value: PropertyType.NUMBER, label: 'Number' },
  { value: PropertyType.BOOLEAN, label: 'Boolean' },
  { value: PropertyType.DATE, label: 'Date' },
  { value: PropertyType.PASSWORD, label: 'Password' },
  { value: PropertyType.SELECT, label: 'List' },
]

const optionsJson = ref('')
const jsonError = ref(false)

watch(() => props.modelValue, (open) => {
  if (open && props.input) {
    const data = props.input.data || [{ name: 'Example', value: 'example', isDefault: true }]
    optionsJson.value = JSON.stringify(data, null, 2)
    jsonError.value = false
  }
})

function onJsonInput(val: string) {
  optionsJson.value = val
  try {
    const parsed = JSON.parse(val)
    if (Array.isArray(parsed) && props.input) {
      props.input.data = parsed
      jsonError.value = false
    } else {
      jsonError.value = true
    }
  } catch {
    jsonError.value = true
  }
}

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue && input" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" @click.self="close">
      <div class="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-sm p-5 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-gray-200">Configure Input</h3>
          <button @click="close" class="text-gray-500 hover:text-gray-300 text-lg leading-none">&times;</button>
        </div>

        <!-- Name -->
        <div>
          <label class="block text-xs text-gray-400 mb-1">Name</label>
          <input v-model="input.name" placeholder="Input name" class="input-sm" />
        </div>

        <!-- Type -->
        <div>
          <label class="block text-xs text-gray-400 mb-1">Type</label>
          <select v-model.number="input.type" class="input-sm">
            <option v-for="t in typeLabels" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
        </div>

        <!-- Required -->
        <label class="flex items-center gap-2 text-sm text-gray-400">
          <input type="checkbox" v-model="input.is_required" />
          Required
        </label>

        <!-- List options editor (only when SELECT) -->
        <div v-if="input.type === PropertyType.SELECT">
          <label class="block text-xs text-gray-400 mb-1">
            Options
            <span v-if="jsonError" class="text-red-400 ml-1">- Invalid JSON</span>
          </label>
          <textarea
            :value="optionsJson"
            @input="onJsonInput(($event.target as HTMLTextAreaElement).value)"
            rows="6"
            class="w-full px-2 py-1.5 bg-gray-800 border rounded text-xs font-mono focus:outline-none"
            :class="jsonError ? 'border-red-500 focus:border-red-500' : 'border-gray-700 focus:border-blue-500'"
            placeholder='[{"name": "Label", "value": "val", "isDefault": true}]'
          />
          <p class="text-[10px] text-gray-600 mt-1">Array of objects with name, value, and optional isDefault.</p>
        </div>

        <div class="flex justify-end pt-1">
          <button @click="close" class="px-4 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-xs transition-colors">
            Done
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
