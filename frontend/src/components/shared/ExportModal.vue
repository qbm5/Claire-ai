<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  modelValue: boolean
  defaultName: string
  defaultDescription: string
  defaultVersion: number
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'confirm': [name: string, description: string, version: number]
}>()

const name = ref('')
const description = ref('')
const version = ref(1)

watch(() => props.modelValue, (open) => {
  if (open) {
    name.value = props.defaultName
    description.value = props.defaultDescription
    version.value = props.defaultVersion || 1
  }
})

function close() {
  emit('update:modelValue', false)
}

function confirm() {
  emit('confirm', name.value, description.value, version.value)
  close()
}
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" @click.self="close">
      <div class="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-sm p-5 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-gray-200">Export</h3>
          <button @click="close" class="text-gray-500 hover:text-gray-300 text-lg leading-none">&times;</button>
        </div>

        <div>
          <label class="block text-xs text-gray-400 mb-1">Name</label>
          <input v-model="name" placeholder="Export name" class="input-sm" />
        </div>

        <div>
          <label class="block text-xs text-gray-400 mb-1">Description</label>
          <textarea v-model="description" rows="3" placeholder="Export description" class="input-sm resize-y" />
        </div>

        <div>
          <label class="block text-xs text-gray-400 mb-1">Version</label>
          <input v-model.number="version" type="number" min="1" class="w-24 px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm focus:outline-none focus:border-blue-500" />
        </div>

        <div class="flex justify-end gap-2 pt-1">
          <button @click="close" class="px-4 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-xs transition-colors">
            Cancel
          </button>
          <button @click="confirm" class="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-medium transition-colors">
            Export
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
