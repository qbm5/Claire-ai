<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'

interface ModelEntry {
  id: string
  name: string
  provider: 'anthropic' | 'openai' | 'google' | 'xai' | 'local'
}

const props = defineProps<{
  modelValue: string
  models: ModelEntry[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const open = ref(false)
const query = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)
const highlightIndex = ref(-1)
const dropdownRef = ref<HTMLDivElement | null>(null)
const dropdownStyle = ref<Record<string, string>>({})

const anthropicModels = computed(() => {
  const q = query.value.toLowerCase().trim()
  const list = props.models.filter(m => m.provider === 'anthropic')
  return q ? list.filter(m => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)) : list
})

const openaiModels = computed(() => {
  const q = query.value.toLowerCase().trim()
  const list = props.models.filter(m => m.provider === 'openai')
  return q ? list.filter(m => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)) : list
})

const geminiModels = computed(() => {
  const q = query.value.toLowerCase().trim()
  const list = props.models.filter(m => m.provider === 'google')
  return q ? list.filter(m => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)) : list
})

const xaiModels = computed(() => {
  const q = query.value.toLowerCase().trim()
  const list = props.models.filter(m => m.provider === 'xai')
  return q ? list.filter(m => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)) : list
})

const localModels = computed(() => {
  const q = query.value.toLowerCase().trim()
  const list = props.models.filter(m => m.provider === 'local')
  return q ? list.filter(m => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)) : list
})

// Flat list for keyboard navigation: Default + Anthropic + OpenAI + Google + xAI + Local
const flatOptions = computed(() => {
  const items: { id: string; label: string; group: string }[] = [
    { id: '', label: 'Default', group: '' },
  ]
  for (const m of anthropicModels.value) items.push({ id: m.id, label: m.name, group: 'Anthropic' })
  for (const m of openaiModels.value) items.push({ id: m.id, label: m.name, group: 'OpenAI' })
  for (const m of geminiModels.value) items.push({ id: m.id, label: m.name, group: 'Google' })
  for (const m of xaiModels.value) items.push({ id: m.id, label: m.name, group: 'xAI' })
  for (const m of localModels.value) items.push({ id: m.id, label: m.name, group: 'Local' })
  return items
})

const displayLabel = computed(() => {
  if (!props.modelValue) return 'Default'
  const m = props.models.find(m => m.id === props.modelValue)
  return m ? m.name : props.modelValue
})

function toggle() {
  open.value = !open.value
  if (open.value) {
    query.value = ''
    highlightIndex.value = -1
    nextTick(() => {
      updatePosition()
      searchInput.value?.focus()
    })
  }
}

function select(id: string) {
  emit('update:modelValue', id)
  open.value = false
  query.value = ''
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    highlightIndex.value = Math.min(highlightIndex.value + 1, flatOptions.value.length - 1)
    scrollToHighlighted()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    highlightIndex.value = Math.max(highlightIndex.value - 1, 0)
    scrollToHighlighted()
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (highlightIndex.value >= 0 && highlightIndex.value < flatOptions.value.length) {
      select(flatOptions.value[highlightIndex.value].id)
    }
  } else if (e.key === 'Escape') {
    open.value = false
  }
}

function scrollToHighlighted() {
  nextTick(() => {
    const el = dropdownRef.value?.querySelector('[data-highlighted="true"]')
    el?.scrollIntoView({ block: 'nearest' })
  })
}

watch(query, () => {
  highlightIndex.value = flatOptions.value.length > 0 ? 0 : -1
})

function updatePosition() {
  const el = containerRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  dropdownStyle.value = {
    position: 'fixed',
    top: `${rect.bottom + 4}px`,
    left: `${rect.left}px`,
    width: `${rect.width}px`,
    zIndex: '9999',
  }
}

function onClickOutside(e: MouseEvent) {
  const target = e.target as Node
  if (containerRef.value?.contains(target)) return
  if (dropdownRef.value?.contains(target)) return
  open.value = false
}

function onScroll(e: Event) {
  if (!open.value) return
  if (dropdownRef.value?.contains(e.target as Node)) return
  open.value = false
}

onMounted(() => {
  document.addEventListener('mousedown', onClickOutside)
  window.addEventListener('scroll', onScroll, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onClickOutside)
  window.removeEventListener('scroll', onScroll, true)
})
</script>

<template>
  <div ref="containerRef" class="relative">
    <!-- Trigger button -->
    <button
      type="button"
      @click="toggle"
      class="w-full flex items-center justify-between px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-left focus:outline-none focus:border-blue-500 hover:border-gray-600 transition-colors"
    >
      <span class="truncate" :class="modelValue ? 'text-gray-200' : 'text-gray-400'">{{ displayLabel }}</span>
      <svg class="w-3.5 h-3.5 text-gray-500 shrink-0 ml-1 transition-transform" :class="{ 'rotate-180': open }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
      </svg>
    </button>

    <!-- Dropdown -->
    <Teleport to="body">
    <div
      v-if="open"
      ref="dropdownRef"
      :style="dropdownStyle"
      class="border border-gray-700 rounded-lg shadow-xl overflow-hidden"
      style="background: #1a1d23;"
    >
      <!-- Search input -->
      <div class="p-1.5 border-b border-gray-700">
        <input
          ref="searchInput"
          v-model="query"
          @keydown="onKeydown"
          placeholder="Search models..."
          class="input-sm placeholder-gray-500"
        />
      </div>

      <!-- Options list -->
      <div class="max-h-64 overflow-auto">
        <!-- Empty state -->
        <div v-if="flatOptions.length <= 1 && !anthropicModels.length && !openaiModels.length" class="px-3 py-4 text-xs text-gray-500 text-center">
          No models available
        </div>

        <!-- Default option (always visible unless searching) -->
        <button
          v-if="!query.trim()"
          @click="select('')"
          :data-highlighted="highlightIndex === 0"
          class="w-full text-left px-3 py-1.5 text-sm transition-colors flex items-center gap-2"
          :class="highlightIndex === 0 ? 'bg-blue-600/30 text-gray-50' : 'text-gray-300 hover:bg-gray-800'"
        >
          <span class="text-gray-400">Default</span>
          <span v-if="!modelValue" class="ml-auto text-blue-400 text-xs">&#10003;</span>
        </button>

        <!-- Anthropic group -->
        <template v-if="anthropicModels.length">
          <div class="px-2 pt-2 pb-1 text-[10px] text-gray-500 uppercase font-medium tracking-wide">Anthropic</div>
          <button
            v-for="m in anthropicModels"
            :key="m.id"
            @click="select(m.id)"
            :data-highlighted="flatOptions.findIndex(f => f.id === m.id) === highlightIndex"
            class="w-full text-left px-3 py-1.5 text-sm transition-colors flex items-center gap-2"
            :class="flatOptions.findIndex(f => f.id === m.id) === highlightIndex ? 'bg-blue-600/30 text-gray-50' : 'text-gray-300 hover:bg-gray-800'"
          >
            <span class="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0"></span>
            <span class="truncate">{{ m.name }}</span>
            <span v-if="modelValue === m.id" class="ml-auto text-blue-400 text-xs">&#10003;</span>
          </button>
        </template>

        <!-- OpenAI group -->
        <template v-if="openaiModels.length">
          <div class="px-2 pt-2 pb-1 text-[10px] text-gray-500 uppercase font-medium tracking-wide">OpenAI</div>
          <button
            v-for="m in openaiModels"
            :key="m.id"
            @click="select(m.id)"
            :data-highlighted="flatOptions.findIndex(f => f.id === m.id) === highlightIndex"
            class="w-full text-left px-3 py-1.5 text-sm transition-colors flex items-center gap-2"
            :class="flatOptions.findIndex(f => f.id === m.id) === highlightIndex ? 'bg-blue-600/30 text-gray-50' : 'text-gray-300 hover:bg-gray-800'"
          >
            <span class="w-1.5 h-1.5 rounded-full bg-green-400 shrink-0"></span>
            <span class="truncate">{{ m.name }}</span>
            <span v-if="modelValue === m.id" class="ml-auto text-blue-400 text-xs">&#10003;</span>
          </button>
        </template>

        <!-- Google group -->
        <template v-if="geminiModels.length">
          <div class="px-2 pt-2 pb-1 text-[10px] text-gray-500 uppercase font-medium tracking-wide">Google</div>
          <button
            v-for="m in geminiModels"
            :key="m.id"
            @click="select(m.id)"
            :data-highlighted="flatOptions.findIndex(f => f.id === m.id) === highlightIndex"
            class="w-full text-left px-3 py-1.5 text-sm transition-colors flex items-center gap-2"
            :class="flatOptions.findIndex(f => f.id === m.id) === highlightIndex ? 'bg-blue-600/30 text-gray-50' : 'text-gray-300 hover:bg-gray-800'"
          >
            <span class="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0"></span>
            <span class="truncate">{{ m.name }}</span>
            <span v-if="modelValue === m.id" class="ml-auto text-blue-400 text-xs">&#10003;</span>
          </button>
        </template>

        <!-- xAI group -->
        <template v-if="xaiModels.length">
          <div class="px-2 pt-2 pb-1 text-[10px] text-gray-500 uppercase font-medium tracking-wide">xAI (Grok)</div>
          <button
            v-for="m in xaiModels"
            :key="m.id"
            @click="select(m.id)"
            :data-highlighted="flatOptions.findIndex(f => f.id === m.id) === highlightIndex"
            class="w-full text-left px-3 py-1.5 text-sm transition-colors flex items-center gap-2"
            :class="flatOptions.findIndex(f => f.id === m.id) === highlightIndex ? 'bg-blue-600/30 text-gray-50' : 'text-gray-300 hover:bg-gray-800'"
          >
            <span class="w-1.5 h-1.5 rounded-full bg-purple-400 shrink-0"></span>
            <span class="truncate">{{ m.name }}</span>
            <span v-if="modelValue === m.id" class="ml-auto text-blue-400 text-xs">&#10003;</span>
          </button>
        </template>

        <!-- Local group -->
        <template v-if="localModels.length">
          <div class="px-2 pt-2 pb-1 text-[10px] text-gray-500 uppercase font-medium tracking-wide">Local</div>
          <button
            v-for="m in localModels"
            :key="m.id"
            @click="select(m.id)"
            :data-highlighted="flatOptions.findIndex(f => f.id === m.id) === highlightIndex"
            class="w-full text-left px-3 py-1.5 text-sm transition-colors flex items-center gap-2"
            :class="flatOptions.findIndex(f => f.id === m.id) === highlightIndex ? 'bg-blue-600/30 text-gray-50' : 'text-gray-300 hover:bg-gray-800'"
          >
            <span class="w-1.5 h-1.5 rounded-full bg-orange-400 shrink-0"></span>
            <span class="truncate">{{ m.name }}</span>
            <span v-if="modelValue === m.id" class="ml-auto text-blue-400 text-xs">&#10003;</span>
          </button>
        </template>
      </div>
    </div>
    </Teleport>
  </div>
</template>
