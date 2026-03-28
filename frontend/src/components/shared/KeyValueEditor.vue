<script setup lang="ts">
import TemplateInput from './TemplateInput.vue'

const props = withDefaults(defineProps<{
  modelValue: { key: string; value: string }[]
  variables: string[]
  label: string
  keyPlaceholder?: string
  valuePlaceholder?: string
}>(), {
  keyPlaceholder: 'Key',
  valuePlaceholder: 'Value',
})

const emit = defineEmits<{
  'update:modelValue': [value: { key: string; value: string }[]]
}>()

function updateKey(idx: number, key: string) {
  const arr = [...props.modelValue]
  arr[idx] = { ...arr[idx], key }
  emit('update:modelValue', arr)
}

function updateValue(idx: number, value: string) {
  const arr = [...props.modelValue]
  arr[idx] = { ...arr[idx], value }
  emit('update:modelValue', arr)
}

function addPair() {
  emit('update:modelValue', [...props.modelValue, { key: '', value: '' }])
}

function removePair(idx: number) {
  const arr = [...props.modelValue]
  arr.splice(idx, 1)
  emit('update:modelValue', arr)
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-1.5">
      <label class="block text-sm text-gray-400">{{ label }}</label>
      <button type="button" @click="addPair" class="text-xs text-blue-400 hover:text-blue-300">+ Add</button>
    </div>

    <div v-if="modelValue.length === 0" class="text-xs text-gray-600 py-2">
      No {{ label.toLowerCase() }} defined
    </div>

    <div v-else class="space-y-1.5">
      <div v-for="(pair, idx) in modelValue" :key="idx" class="flex items-start gap-1.5">
        <input
          :value="pair.key"
          @input="updateKey(idx, ($event.target as HTMLInputElement).value)"
          :placeholder="keyPlaceholder"
          class="w-[35%] shrink-0 px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm focus:outline-none focus:border-blue-500"
        />
        <div class="flex-1 min-w-0">
          <TemplateInput
            :modelValue="pair.value"
            @update:modelValue="updateValue(idx, $event)"
            :variables="variables"
            mode="input"
            :placeholder="valuePlaceholder"
            inputClass="input-sm"
          />
        </div>
        <button type="button" @click="removePair(idx)" class="shrink-0 px-1.5 py-1.5 text-red-400 hover:text-red-300 text-sm" title="Remove">
          &times;
        </button>
      </div>
    </div>
  </div>
</template>
