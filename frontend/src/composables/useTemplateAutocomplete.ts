import { ref, computed, type Ref } from 'vue'

export interface TemplateAutocompleteOptions {
  variables: Ref<string[]>
  onInsert: (fullText: string, cursorPos: number) => void
}

export function useTemplateAutocomplete(options: TemplateAutocompleteOptions) {
  const isOpen = ref(false)
  const activeIndex = ref(0)
  const partialText = ref('')
  const matchStart = ref(-1)

  const filtered = computed(() => {
    const partial = partialText.value.toLowerCase()
    return options.variables.value.filter(v => v.toLowerCase().includes(partial))
  })

  /**
   * Detect `{{` context from text before cursor.
   * Returns the partial string after `{{`, or null if not in template context.
   */
  function detectContext(text: string, cursorPos: number): { partial: string; start: number } | null {
    const before = text.slice(0, cursorPos)
    const match = before.match(/\{\{([^}]*)$/)
    if (!match) return null
    return {
      partial: match[1],
      start: before.length - match[0].length,
    }
  }

  function onInput(text: string, cursorPos: number) {
    const ctx = detectContext(text, cursorPos)
    if (ctx && options.variables.value.length > 0) {
      partialText.value = ctx.partial
      matchStart.value = ctx.start
      isOpen.value = filtered.value.length > 0
      activeIndex.value = 0
    } else {
      close()
    }
  }

  function close() {
    isOpen.value = false
    activeIndex.value = 0
    partialText.value = ''
    matchStart.value = -1
  }

  function select(text: string, cursorPos: number, varName: string): { newText: string; newCursor: number } {
    const replacement = `{{${varName}}}`
    const before = text.slice(0, matchStart.value)
    const after = text.slice(cursorPos)
    const newText = before + replacement + after
    const newCursor = before.length + replacement.length
    close()
    return { newText, newCursor }
  }

  /**
   * Handle keyboard events when dropdown is open.
   * Returns true if the event was handled (should preventDefault).
   */
  function onKeyDown(e: KeyboardEvent, text: string, cursorPos: number): { handled: boolean; newText?: string; newCursor?: number } {
    if (!isOpen.value || filtered.value.length === 0) {
      return { handled: false }
    }

    switch (e.key) {
      case 'ArrowDown':
        activeIndex.value = (activeIndex.value + 1) % filtered.value.length
        return { handled: true }
      case 'ArrowUp':
        activeIndex.value = (activeIndex.value - 1 + filtered.value.length) % filtered.value.length
        return { handled: true }
      case 'Enter':
      case 'Tab': {
        const varName = filtered.value[activeIndex.value]
        const result = select(text, cursorPos, varName)
        return { handled: true, ...result }
      }
      case 'Escape':
        close()
        return { handled: true }
      default:
        return { handled: false }
    }
  }

  return {
    isOpen,
    activeIndex,
    filtered,
    onInput,
    onKeyDown,
    select,
    close,
  }
}
