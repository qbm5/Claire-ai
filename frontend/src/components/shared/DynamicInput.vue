<script setup lang="ts">
import { PropertyType } from '@/models'
import ExpandableTextInput from './ExpandableTextInput.vue'

defineProps<{
  modelValue: any
  type?: PropertyType
  placeholder?: string
  label?: string
  data?: { name: string; value: string; isDefault?: boolean }[]
  variables?: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: any]
}>()
</script>

<template>
  <!-- BOOLEAN -->
  <label v-if="type === PropertyType.BOOLEAN" class="flex items-center gap-2">
    <input
      type="checkbox"
      :checked="!!modelValue"
      @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
      class="rounded bg-gray-800 border-gray-600 text-blue-500 focus:ring-blue-500"
    />
    <span class="text-xs text-gray-400">{{ modelValue ? 'Yes' : 'No' }}</span>
  </label>

  <!-- NUMBER -->
  <input
    v-else-if="type === PropertyType.NUMBER"
    type="number"
    :value="modelValue"
    @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    :placeholder="placeholder"
    class="w-full px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500"
  />

  <!-- DATE -->
  <input
    v-else-if="type === PropertyType.DATE"
    type="date"
    :value="modelValue"
    @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    class="w-full px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500"
  />

  <!-- PASSWORD -->
  <input
    v-else-if="type === PropertyType.PASSWORD"
    type="password"
    :value="modelValue"
    @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    :placeholder="placeholder"
    class="w-full px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500"
  />

  <!-- SELECT -->
  <select
    v-else-if="type === PropertyType.SELECT"
    :value="modelValue"
    @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
    class="w-full px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500"
  >
    <option value="">-- Select --</option>
    <option v-for="opt in (data || [])" :key="opt.value" :value="opt.value">{{ opt.name }}</option>
  </select>

  <!-- TEXT (default) -->
  <ExpandableTextInput
    v-else
    :modelValue="modelValue ?? ''"
    @update:modelValue="emit('update:modelValue', $event)"
    :placeholder="placeholder"
    :label="label"
    :variables="variables"
  />
</template>
