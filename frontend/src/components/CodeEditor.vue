<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, shallowRef, computed } from 'vue'
import * as monaco from 'monaco-editor'
import { didOpen, didChange, didClose } from '@/services/lspClient'
import { useTheme } from '@/composables/useTheme'

const { theme } = useTheme()
const monacoTheme = computed(() => theme.value === 'dark' ? 'vs-dark' : 'vs')

// Set up Monaco workers
self.MonacoEnvironment = {
  getWorker(_workerId: string, label: string) {
    if (label === 'json') {
      return new Worker(
        new URL('monaco-editor/esm/vs/language/json/json.worker.js', import.meta.url),
        { type: 'module' }
      )
    }
    if (label === 'css' || label === 'scss' || label === 'less') {
      return new Worker(
        new URL('monaco-editor/esm/vs/language/css/css.worker.js', import.meta.url),
        { type: 'module' }
      )
    }
    if (label === 'html' || label === 'handlebars' || label === 'razor') {
      return new Worker(
        new URL('monaco-editor/esm/vs/language/html/html.worker.js', import.meta.url),
        { type: 'module' }
      )
    }
    if (label === 'typescript' || label === 'javascript') {
      return new Worker(
        new URL('monaco-editor/esm/vs/language/typescript/ts.worker.js', import.meta.url),
        { type: 'module' }
      )
    }
    return new Worker(
      new URL('monaco-editor/esm/vs/editor/editor.worker.js', import.meta.url),
      { type: 'module' }
    )
  },
}

const props = withDefaults(defineProps<{
  modelValue: string
  language?: string
  height?: string
  readOnly?: boolean
  fileUri?: string
}>(), {
  language: 'javascript',
  height: '200px',
  readOnly: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const container = ref<HTMLDivElement>()
const editor = shallowRef<monaco.editor.IStandaloneCodeEditor>()
let changeTimer: ReturnType<typeof setTimeout> | undefined
// Capture the URI used at mount time — props.fileUri can change reactively
// (e.g. when trigger data loads) but the Monaco model URI is immutable.
let mountedUri: string | undefined

onMounted(() => {
  if (!container.value) return

  mountedUri = props.fileUri

  // When fileUri is provided, create a model with that URI so LSP providers can match it
  let model: monaco.editor.ITextModel | undefined
  if (mountedUri) {
    const uri = monaco.Uri.parse(mountedUri)
    // Dispose any stale model with this URI
    const existing = monaco.editor.getModel(uri)
    if (existing) existing.dispose()
    model = monaco.editor.createModel(props.modelValue || '', props.language, uri)
  }

  editor.value = monaco.editor.create(container.value, {
    model: model ?? undefined,
    value: model ? undefined : (props.modelValue || ''),
    language: model ? undefined : props.language,
    theme: monacoTheme.value,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    fontSize: 13,
    tabSize: 2,
    automaticLayout: true,
    readOnly: props.readOnly,
  })

  // Notify LSP of document open
  if (mountedUri) {
    didOpen(mountedUri, props.language, props.modelValue || '')
  }

  editor.value.onDidChangeModelContent(() => {
    const val = editor.value!.getValue()
    if (val !== props.modelValue) {
      emit('update:modelValue', val)
    }
    // Debounced LSP change notification
    if (mountedUri) {
      clearTimeout(changeTimer)
      changeTimer = setTimeout(() => {
        didChange(mountedUri!, editor.value!.getValue())
      }, 300)
    }
  })
})

watch(() => props.modelValue, (newVal) => {
  if (editor.value && newVal !== editor.value.getValue()) {
    editor.value.setValue(newVal || '')
  }
})

watch(() => props.readOnly, (val) => {
  editor.value?.updateOptions({ readOnly: val })
})

watch(() => props.language, (val) => {
  const model = editor.value?.getModel()
  if (model) monaco.editor.setModelLanguage(model, val)
})

watch(monacoTheme, (val) => {
  monaco.editor.setTheme(val)
})

onBeforeUnmount(() => {
  clearTimeout(changeTimer)
  if (mountedUri) {
    didClose(mountedUri)
  }
  const model = editor.value?.getModel()
  editor.value?.dispose()
  if (mountedUri && model) {
    model.dispose()
  }
})
</script>

<template>
  <div ref="container" :style="{ height, width: '100%' }"></div>
</template>
