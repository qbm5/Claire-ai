<script setup lang="ts">
import type { ResponseField } from '@/models'

const props = withDefaults(defineProps<{
  modelValue: ResponseField[]
  depth?: number
}>(), { depth: 0 })

const emit = defineEmits<{ 'update:modelValue': [value: ResponseField[]] }>()

function update(index: number, field: Partial<ResponseField>) {
  const copy = props.modelValue.map((f, i) => i === index ? { ...f, ...field } : f)
  // When switching away from object, drop children
  if (field.type && field.type !== 'object') {
    copy[index] = { ...copy[index], children: undefined }
  }
  // When switching to object, init children array
  if (field.type === 'object' && !copy[index].children) {
    copy[index] = { ...copy[index], children: [] }
  }
  emit('update:modelValue', copy)
}

function addField() {
  emit('update:modelValue', [...props.modelValue, { key: '', type: 'string' }])
}

function removeField(index: number) {
  emit('update:modelValue', props.modelValue.filter((_, i) => i !== index))
}

function updateChildren(index: number, children: ResponseField[]) {
  const copy = [...props.modelValue]
  copy[index] = { ...copy[index], children }
  emit('update:modelValue', copy)
}
</script>

<template>
  <div class="space-y-1" :style="{ paddingLeft: depth > 0 ? '16px' : '0' }">
    <div v-for="(field, idx) in modelValue" :key="idx">
      <div class="flex items-center gap-1.5">
        <input
          :value="field.key"
          @input="update(idx, { key: ($event.target as HTMLInputElement).value })"
          placeholder="field name"
          class="flex-1 px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500"
        />
        <select
          :value="field.type"
          @change="update(idx, { type: ($event.target as HTMLSelectElement).value as ResponseField['type'] })"
          class="px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500"
        >
          <option value="string">string</option>
          <option value="number">number</option>
          <option value="boolean">boolean</option>
          <option value="object">object</option>
        </select>
        <button @click="removeField(idx)" class="text-red-400 hover:text-red-300 text-xs shrink-0">&times;</button>
      </div>
      <ResponseStructureEditor
        v-if="field.type === 'object'"
        :modelValue="field.children || []"
        @update:modelValue="updateChildren(idx, $event)"
        :depth="depth + 1"
      />
    </div>
    <button @click="addField" class="text-xs text-blue-400 hover:text-blue-300">+ Add Field</button>
  </div>
</template>
