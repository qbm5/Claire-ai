<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { ToolTypeLabels, type AiTool, type ToolType } from '@/models'
import LetterAvatar from '@/components/shared/LetterAvatar.vue'

interface BuiltinOption {
  id: string
  label: string
  group: 'Special' | 'Base'
}

const builtins: BuiltinOption[] = [
  { id: '-3', label: 'If', group: 'Special' },
  { id: '-4', label: 'Loop Counter', group: 'Special' },
  { id: '-6', label: 'Wait', group: 'Special' },
  { id: '-5', label: 'End', group: 'Special' },
  { id: '-7', label: 'Ask User', group: 'Special' },
  { id: '-8', label: 'File Upload', group: 'Special' },
  { id: '-11', label: 'Task', group: 'Special' },
  { id: '-1', label: 'Base LLM', group: 'Base' },
  { id: '-2', label: 'Base Endpoint', group: 'Base' },
]

const props = defineProps<{
  modelValue: string
  tools: AiTool[]
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

const selectedTool = computed(() => {
  if (!props.modelValue || props.modelValue.startsWith('-')) return null
  return props.tools.find(t => t.id === props.modelValue) || null
})

const displayLabel = computed(() => {
  if (!props.modelValue) return '-- Select --'
  const builtin = builtins.find(b => b.id === props.modelValue)
  if (builtin) return builtin.label
  const tool = selectedTool.value
  if (tool) return `${tool.name} (${ToolTypeLabels[tool.type as ToolType] || ''})`
  return '-- Select --'
})

const filteredBuiltins = computed(() => {
  const q = query.value.toLowerCase().trim()
  if (!q) return builtins
  return builtins.filter(b => b.label.toLowerCase().includes(q))
})

const filteredTools = computed(() => {
  const q = query.value.toLowerCase().trim()
  if (!q) return props.tools
  return props.tools.filter(t =>
    t.name.toLowerCase().includes(q) || (t.tag && t.tag.toLowerCase().includes(q))
  )
})

const specialOptions = computed(() => filteredBuiltins.value.filter(b => b.group === 'Special'))
const baseOptions = computed(() => filteredBuiltins.value.filter(b => b.group === 'Base'))

// Flat list of all visible options for keyboard navigation
const flatOptions = computed(() => {
  const items: { id: string; label: string; group: string }[] = []
  for (const b of specialOptions.value) items.push({ id: b.id, label: b.label, group: 'Special' })
  for (const b of baseOptions.value) items.push({ id: b.id, label: b.label, group: 'Base' })
  for (const t of filteredTools.value) items.push({ id: t.id, label: `${t.name} (${ToolTypeLabels[t.type as ToolType] || ''})`, group: 'Saved Tools' })
  return items
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

// Reset highlight when query changes
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

// Click outside to close
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
      <img v-if="selectedTool?.image_url" :src="selectedTool.image_url" class="w-5 h-5 rounded object-cover shrink-0 bg-black" />
      <LetterAvatar v-else-if="selectedTool" :letter="selectedTool.name" :size="20" />
      <span class="truncate" :class="modelValue ? 'text-gray-200' : 'text-gray-500'">{{ displayLabel }}</span>
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
          placeholder="Search by name or tag..."
          class="input-sm placeholder-gray-500"
        />
      </div>

      <!-- Options list -->
      <div class="max-h-64 overflow-auto">
        <!-- Empty state -->
        <div v-if="flatOptions.length === 0" class="px-3 py-4 text-xs text-gray-500 text-center">
          No matches found
        </div>

        <!-- Special group -->
        <template v-if="specialOptions.length">
          <div class="px-2 pt-2 pb-1 text-[10px] text-gray-500 uppercase font-medium tracking-wide">Special</div>
          <button
            v-for="(opt, i) in specialOptions"
            :key="opt.id"
            @click="select(opt.id)"
            :data-highlighted="flatOptions.indexOf(opt as any) === highlightIndex"
            class="w-full text-left px-3 py-1.5 text-sm transition-colors flex items-center gap-2"
            :class="flatOptions.findIndex(f => f.id === opt.id) === highlightIndex ? 'bg-blue-600/30 text-gray-50' : 'text-gray-300 hover:bg-gray-800'"
          >
            <span class="w-1.5 h-1.5 rounded-full bg-cyan-400 shrink-0" v-if="opt.id === '-3'"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-teal-400 shrink-0" v-else-if="opt.id === '-4'"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" v-else-if="opt.id === '-6'"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0" v-else-if="opt.id === '-5'"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-indigo-400 shrink-0" v-else-if="opt.id === '-7'"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-sky-400 shrink-0" v-else-if="opt.id === '-8'"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-sky-400 shrink-0" v-else-if="opt.id === '-9'"></span>
            {{ opt.label }}
            <span v-if="modelValue === opt.id" class="ml-auto text-blue-400 text-xs">&#10003;</span>
          </button>
        </template>

        <!-- Base group -->
        <template v-if="baseOptions.length">
          <div class="px-2 pt-2 pb-1 text-[10px] text-gray-500 uppercase font-medium tracking-wide">Base</div>
          <button
            v-for="opt in baseOptions"
            :key="opt.id"
            @click="select(opt.id)"
            class="w-full text-left px-3 py-1.5 text-sm transition-colors flex items-center gap-2"
            :class="flatOptions.findIndex(f => f.id === opt.id) === highlightIndex ? 'bg-blue-600/30 text-gray-50' : 'text-gray-300 hover:bg-gray-800'"
          >
            <span class="w-1.5 h-1.5 rounded-full bg-purple-400 shrink-0" v-if="opt.id === '-1'"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-green-400 shrink-0" v-else-if="opt.id === '-2'"></span>
            {{ opt.label }}
            <span v-if="modelValue === opt.id" class="ml-auto text-blue-400 text-xs">&#10003;</span>
          </button>
        </template>

        <!-- Saved Tools group -->
        <template v-if="filteredTools.length">
          <div class="px-2 pt-2 pb-1 text-[10px] text-gray-500 uppercase font-medium tracking-wide">Saved Tools</div>
          <button
            v-for="t in filteredTools"
            :key="t.id"
            @click="select(t.id)"
            class="w-full text-left px-3 py-1.5 text-sm transition-colors"
            :class="flatOptions.findIndex(f => f.id === t.id) === highlightIndex ? 'bg-blue-600/30 text-gray-50' : 'text-gray-300 hover:bg-gray-800'"
          >
            <div class="flex items-center gap-2">
              <img v-if="t.image_url" :src="t.image_url" class="w-5 h-5 rounded object-cover shrink-0 bg-black" />
              <LetterAvatar v-else :letter="t.name" :size="20" />
              <span class="truncate">{{ t.name }}</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-700 text-gray-400 shrink-0">{{ ToolTypeLabels[t.type as ToolType] }}</span>
              <span v-if="modelValue === t.id" class="ml-auto text-blue-400 text-xs shrink-0">&#10003;</span>
            </div>
            <div v-if="t.tag" class="text-[10px] text-gray-500 mt-0.5">{{ t.tag }}</div>
          </button>
        </template>
      </div>
    </div>
    </Teleport>
  </div>
</template>
