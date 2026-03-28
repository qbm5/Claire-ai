<script setup lang="ts">
import { ref, computed, toRef, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useTemplateAutocomplete } from '@/composables/useTemplateAutocomplete'

const props = withDefaults(defineProps<{
  modelValue: string
  variables: string[]
  mode?: 'input' | 'textarea'
  placeholder?: string
  rows?: number
  inputClass?: string
}>(), {
  mode: 'input',
  rows: 3,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const inputRef = ref<HTMLInputElement | HTMLTextAreaElement | null>(null)
const backdropRef = ref<HTMLElement | null>(null)
const dropdownRef = ref<HTMLElement | null>(null)
const dropdownAbove = ref(false)

const variablesRef = toRef(props, 'variables')
const hasVariables = computed(() => props.variables.length > 0)

const { isOpen, activeIndex, filtered, onInput, onKeyDown, select, close } = useTemplateAutocomplete({
  variables: variablesRef,
  onInsert: () => {},
})

// ── Highlight overlay ──

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

const highlightedHtml = computed(() => {
  const text = props.modelValue || ''
  if (!text) return '\n'

  const varSet = new Set(props.variables)
  const regex = /\{\{([^}]+)\}\}/g

  let result = ''
  let lastIndex = 0
  let match

  while ((match = regex.exec(text)) !== null) {
    result += escapeHtml(text.slice(lastIndex, match.index))
    const varName = match[1].trim()
    const isValid = varSet.has(varName)
    const color = isValid ? '#4ade80' : '#f87171'
    result += `<span style="color:${color}">${escapeHtml(match[0])}</span>`
    lastIndex = match.index + match[0].length
  }

  result += escapeHtml(text.slice(lastIndex))
  result += '\n'
  return result
})

// Sync backdrop dimensions to exactly match the textarea's content area.
// clientWidth/clientHeight exclude the scrollbar, so the backdrop always
// matches regardless of whether a scrollbar is visible.
function syncDimensions() {
  const el = inputRef.value
  const bd = backdropRef.value
  if (!el || !bd) return

  const cs = getComputedStyle(el)

  // Position backdrop over the textarea's padding box (inside border)
  bd.style.top = cs.borderTopWidth
  bd.style.left = cs.borderLeftWidth
  // clientWidth/clientHeight exclude scrollbar and border, include padding
  bd.style.width = el.clientWidth + 'px'
  bd.style.height = el.clientHeight + 'px'

  // Match padding so text reflows identically
  bd.style.paddingTop = cs.paddingTop
  bd.style.paddingRight = cs.paddingRight
  bd.style.paddingBottom = cs.paddingBottom
  bd.style.paddingLeft = cs.paddingLeft

  // Match text rendering styles
  bd.style.fontSize = cs.fontSize
  bd.style.fontFamily = cs.fontFamily
  bd.style.fontWeight = cs.fontWeight
  bd.style.lineHeight = cs.lineHeight
  bd.style.letterSpacing = cs.letterSpacing
  bd.style.wordSpacing = cs.wordSpacing
}

function syncScroll() {
  syncDimensions()
  if (backdropRef.value && inputRef.value) {
    backdropRef.value.scrollTop = inputRef.value.scrollTop
    backdropRef.value.scrollLeft = inputRef.value.scrollLeft
  }
}

// ── Input handling ──

function handleInput(e: Event) {
  const el = e.target as HTMLInputElement | HTMLTextAreaElement
  emit('update:modelValue', el.value)
  nextTick(() => {
    onInput(el.value, el.selectionStart ?? el.value.length)
    syncScroll()
  })
}

function handleKeyDown(e: KeyboardEvent) {
  const el = inputRef.value
  if (!el) return
  const result = onKeyDown(e, props.modelValue, el.selectionStart ?? props.modelValue.length)
  if (result.handled) {
    e.preventDefault()
    if (result.newText !== undefined) {
      emit('update:modelValue', result.newText)
      nextTick(() => {
        if (el && result.newCursor !== undefined) {
          el.setSelectionRange(result.newCursor, result.newCursor)
        }
        syncScroll()
      })
    }
  }
}

function handleSelect(varName: string) {
  const el = inputRef.value
  if (!el) return
  const cursorPos = el.selectionStart ?? props.modelValue.length
  const result = select(props.modelValue, cursorPos, varName)
  emit('update:modelValue', result.newText)
  nextTick(() => {
    el.focus()
    el.setSelectionRange(result.newCursor, result.newCursor)
    syncScroll()
  })
}

function handleClickOutside(e: MouseEvent) {
  if (
    dropdownRef.value && !dropdownRef.value.contains(e.target as Node) &&
    inputRef.value && !inputRef.value.contains(e.target as Node)
  ) {
    close()
  }
}

function checkFlip() {
  if (!inputRef.value) return
  const rect = inputRef.value.getBoundingClientRect()
  const spaceBelow = window.innerHeight - rect.bottom
  dropdownAbove.value = spaceBelow < 180
}

let resizeObs: ResizeObserver | null = null

onMounted(() => {
  document.addEventListener('mousedown', handleClickOutside)
  nextTick(() => {
    syncDimensions()
    if (inputRef.value) {
      resizeObs = new ResizeObserver(() => syncDimensions())
      resizeObs.observe(inputRef.value)
    }
  })
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleClickOutside)
  resizeObs?.disconnect()
})

watch(() => props.modelValue, () => {
  nextTick(syncDimensions)
})
</script>

<template>
  <div class="relative w-full">
    <!-- Highlight backdrop: sized via JS to match textarea's content area exactly -->
    <div
      v-if="hasVariables"
      ref="backdropRef"
      class="template-backdrop"
      :class="mode === 'textarea' ? 'template-backdrop-textarea' : 'template-backdrop-input'"
      aria-hidden="true"
      v-html="highlightedHtml"
    />

    <input
      v-if="mode === 'input'"
      ref="inputRef"
      :value="modelValue"
      @input="handleInput"
      @keydown="handleKeyDown"
      @click="checkFlip"
      @scroll="syncScroll"
      :placeholder="placeholder"
      :class="[inputClass, 'w-full', { 'template-highlight': hasVariables }]"
      :style="hasVariables ? { position: 'relative', background: 'transparent', color: 'transparent', caretColor: 'var(--color-gray-300)', zIndex: 1 } : {}"
    />
    <textarea
      v-else
      ref="inputRef"
      :value="modelValue"
      @input="handleInput"
      @keydown="handleKeyDown"
      @click="checkFlip"
      @scroll="syncScroll"
      :placeholder="placeholder"
      :rows="rows"
      :class="[inputClass, 'w-full', { 'template-highlight': hasVariables }]"
      :style="hasVariables ? { position: 'relative', background: 'transparent', color: 'transparent', caretColor: 'var(--color-gray-300)', zIndex: 1 } : {}"
    />

    <!-- Autocomplete dropdown -->
    <div
      v-if="isOpen && filtered.length > 0"
      ref="dropdownRef"
      class="absolute left-0 right-0 z-50 bg-gray-800 border border-gray-600 rounded-lg shadow-xl overflow-auto"
      :class="dropdownAbove ? 'bottom-full mb-1' : 'top-full mt-1'"
      style="max-height: 160px;"
    >
      <button
        v-for="(varName, idx) in filtered"
        :key="varName"
        type="button"
        class="w-full text-left px-3 py-1.5 text-xs font-mono transition-colors"
        :class="idx === activeIndex ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-700'"
        @mousedown.prevent="handleSelect(varName)"
        @mouseenter="activeIndex = idx"
      >
        <span class="text-gray-500" v-pre>{{</span><span class="font-semibold">{{ varName }}</span><span class="text-gray-500" v-pre>}}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
/* Backdrop: position/size/padding/font are set via JS to match the textarea exactly */
.template-backdrop {
  position: absolute;
  overflow: hidden;
  pointer-events: none;
  resize: none;
  z-index: 0;
  color: var(--color-gray-300);
  box-sizing: border-box;
  border: none;
  margin: 0;
}
.template-backdrop-textarea {
  white-space: pre-wrap;
  overflow-wrap: break-word;
}
.template-backdrop-input {
  white-space: nowrap;
  overflow-wrap: normal;
}
.template-highlight::placeholder {
  color: var(--color-gray-500);
}
</style>
