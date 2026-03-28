<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'

const NO_TAG = '__no_tag__'

const props = defineProps<{
  tags: string[]
  modelValue: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [tags: string[]]
}>()

const open = ref(false)
const tagSearch = ref('')
const wrapperRef = ref<HTMLElement>()
const dropdownRef = ref<HTMLElement>()
const dropdownStyle = ref<Record<string, string>>({})

const filteredTags = computed(() => {
  const q = tagSearch.value.toLowerCase()
  if (!q) return props.tags
  return props.tags.filter(t =>
    t === NO_TAG ? 'no tag'.includes(q) : t.toLowerCase().includes(q)
  )
})

const activeCount = computed(() => props.modelValue.length)

function isChecked(tag: string) {
  return props.modelValue.includes(tag)
}

function toggle(tag: string) {
  const current = [...props.modelValue]
  const idx = current.indexOf(tag)
  if (idx >= 0) {
    current.splice(idx, 1)
  } else {
    current.push(tag)
  }
  emit('update:modelValue', current)
}

function clearAll() {
  emit('update:modelValue', [])
}

function updatePosition() {
  const btn = wrapperRef.value?.querySelector('button')
  if (!btn) return
  const rect = btn.getBoundingClientRect()
  const dropdownHeight = 300
  const spaceBelow = window.innerHeight - rect.bottom

  if (spaceBelow < dropdownHeight && rect.top > dropdownHeight) {
    dropdownStyle.value = {
      position: 'fixed',
      bottom: `${window.innerHeight - rect.top + 4}px`,
      right: `${window.innerWidth - rect.right}px`,
      width: '16rem',
      zIndex: '9999',
    }
  } else {
    dropdownStyle.value = {
      position: 'fixed',
      top: `${rect.bottom + 4}px`,
      right: `${window.innerWidth - rect.right}px`,
      width: '16rem',
      zIndex: '9999',
    }
  }
}

async function toggleOpen() {
  open.value = !open.value
  if (open.value) {
    tagSearch.value = ''
    await nextTick()
    updatePosition()
  }
}

function onClickOutside(e: MouseEvent) {
  const target = e.target as Node
  if (wrapperRef.value?.contains(target)) return
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
  <div ref="wrapperRef" class="relative shrink-0">
    <button
      @click="toggleOpen"
      class="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors border"
      :class="activeCount > 0
        ? 'bg-blue-600/20 text-blue-400 border-blue-600/40 hover:bg-blue-600/30'
        : 'bg-gray-800 text-gray-400 border-gray-700 hover:bg-gray-700 hover:text-gray-300'"
    >
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
      </svg>
      Filter
      <span
        v-if="activeCount > 0"
        class="ml-0.5 px-1.5 py-0.5 text-[10px] font-bold bg-blue-600 text-white rounded-full leading-none"
      >{{ activeCount }}</span>
    </button>

    <Teleport to="body">
    <div
      v-if="open"
      ref="dropdownRef"
      :style="dropdownStyle"
      class="bg-gray-900 border border-gray-700 rounded-lg shadow-xl overflow-hidden"
    >
      <div class="p-2 border-b border-gray-800">
        <input
          v-model="tagSearch"
          placeholder="Search tags..."
          class="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-gray-200 focus:outline-none focus:border-blue-500 placeholder-gray-500"
          @keydown.stop
        />
      </div>

      <div class="max-h-56 overflow-y-auto">
        <div v-if="filteredTags.length === 0" class="px-3 py-4 text-sm text-gray-500 text-center">
          No tags found
        </div>
        <label
          v-for="tag in filteredTags"
          :key="tag"
          class="flex items-center gap-2.5 px-3 py-1.5 text-sm cursor-pointer hover:bg-gray-800/60 transition-colors select-none"
        >
          <input
            type="checkbox"
            :checked="isChecked(tag)"
            @change="toggle(tag)"
            class="accent-blue-500 shrink-0"
          />
          <span v-if="tag === '__no_tag__'" class="text-gray-500 italic">No Tag</span>
          <span v-else class="text-gray-300 truncate">{{ tag }}</span>
        </label>
      </div>

      <div v-if="activeCount > 0" class="p-2 border-t border-gray-800">
        <button
          @click="clearAll"
          class="w-full px-3 py-1 text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded transition-colors"
        >Clear all filters</button>
      </div>
    </div>
    </Teleport>
  </div>
</template>
