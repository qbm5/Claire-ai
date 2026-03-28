<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'

export interface UserOption {
  id: string
  username: string
  display_name?: string
}

const props = defineProps<{
  modelValue: string
  users: UserOption[]
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

const displayLabel = computed(() => {
  if (!props.modelValue) return 'All Users'
  const u = props.users.find(u => u.id === props.modelValue)
  if (u) return u.display_name || u.username
  return 'All Users'
})

const filteredUsers = computed(() => {
  const q = query.value.toLowerCase().trim()
  if (!q) return props.users
  return props.users.filter(u =>
    u.username.toLowerCase().includes(q) ||
    (u.display_name && u.display_name.toLowerCase().includes(q))
  )
})

// +1 for the "All Users" option at index 0
const totalOptions = computed(() => filteredUsers.value.length + 1)

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
    highlightIndex.value = Math.min(highlightIndex.value + 1, totalOptions.value - 1)
    scrollToHighlighted()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    highlightIndex.value = Math.max(highlightIndex.value - 1, 0)
    scrollToHighlighted()
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (highlightIndex.value === 0) {
      select('')
    } else if (highlightIndex.value > 0 && highlightIndex.value <= filteredUsers.value.length) {
      select(filteredUsers.value[highlightIndex.value - 1].id)
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
  highlightIndex.value = totalOptions.value > 0 ? 0 : -1
})

function updatePosition() {
  const el = containerRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  dropdownStyle.value = {
    position: 'fixed',
    top: `${rect.bottom + 4}px`,
    left: `${rect.left}px`,
    width: '14rem',
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
      class="flex items-center gap-1.5 px-2 py-1 bg-gray-800 border border-gray-700 rounded-lg text-xs text-left focus:outline-none focus:border-blue-500 hover:border-gray-600 transition-colors"
    >
      <svg class="w-3.5 h-3.5 text-gray-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
      </svg>
      <span class="truncate max-w-[120px]" :class="modelValue ? 'text-gray-200' : 'text-gray-400'">{{ displayLabel }}</span>
      <svg class="w-3 h-3 text-gray-500 shrink-0 transition-transform" :class="{ 'rotate-180': open }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
          placeholder="Search users..."
          class="input-sm placeholder-gray-500"
        />
      </div>

      <!-- Options list -->
      <div class="max-h-64 overflow-auto">
        <div v-if="totalOptions === 1 && filteredUsers.length === 0" class="px-3 py-4 text-xs text-gray-500 text-center">
          No matches found
        </div>

        <!-- All Users option -->
        <button
          @click="select('')"
          :data-highlighted="highlightIndex === 0"
          class="w-full text-left px-3 py-1.5 text-sm transition-colors flex items-center gap-2"
          :class="highlightIndex === 0 ? 'bg-blue-600/30 text-gray-50' : 'text-gray-300 hover:bg-gray-800'"
        >
          All Users
          <span v-if="!modelValue" class="ml-auto text-blue-400 text-xs">&#10003;</span>
        </button>

        <!-- User list -->
        <div class="px-2 pt-2 pb-1 text-[10px] text-gray-500 uppercase font-medium tracking-wide">Users</div>
        <button
          v-for="(u, i) in filteredUsers"
          :key="u.id"
          @click="select(u.id)"
          :data-highlighted="highlightIndex === i + 1"
          class="w-full text-left px-3 py-1.5 text-sm transition-colors"
          :class="highlightIndex === i + 1 ? 'bg-blue-600/30 text-gray-50' : 'text-gray-300 hover:bg-gray-800'"
        >
          <div class="flex items-center gap-2">
            <span class="truncate">{{ u.display_name || u.username }}</span>
            <span v-if="modelValue === u.id" class="ml-auto text-blue-400 text-xs shrink-0">&#10003;</span>
          </div>
          <div v-if="u.display_name && u.display_name !== u.username" class="text-[10px] text-gray-500 mt-0.5">@{{ u.username }}</div>
        </button>
      </div>
    </div>
    </Teleport>
  </div>
</template>
