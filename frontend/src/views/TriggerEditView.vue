<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { getTrigger, saveTrigger, deleteTrigger, fireTrigger, wsAiAssistTrigger, uploadTriggerImage, deleteTriggerImage } from '@/services/triggerService'
import { useImageUpload } from '@/composables/useImageUpload'
import type { TriggerAiAssistEvent } from '@/services/triggerService'
import { getPipelines, getPipeline } from '@/services/pipelineService'
import { imageUrlToBase64 } from '@/services/api'
import {
  createTrigger, TriggerType, TriggerTypeLabels, PropertyType, getUid,
  type AiTrigger, type AiPipeline, type TriggerConnection, type EnvVariable,
} from '@/models'
import { deepClone } from '@/utils/clone'
import type { PipResult } from '@/services/triggerService'
import CodeEditor from '@/components/CodeEditor.vue'
import ExportModal from '@/components/shared/ExportModal.vue'
import LetterAvatar from '@/components/shared/LetterAvatar.vue'
import TemplateInput from '@/components/shared/TemplateInput.vue'
import ModelSelectDropdown from '@/components/shared/ModelSelectDropdown.vue'
import { useModels, loadModels } from '@/composables/useModels'
import { getCustomSettings, saveCustomSettings } from '@/services/settingsService'
import { useToast } from '@/composables/useToast'

const { show: toast } = useToast()
const { models } = useModels()
const auth = useAuth()
const props = defineProps<{ id: string }>()
const router = useRouter()
const route = useRoute()

const trigger = ref<AiTrigger>(createTrigger())
const loading = ref(false)
const pipelines = ref<AiPipeline[]>([])

// Image upload
const { imageFileInput, uploadingImage, onImageSelected: _onImageSelected, removeImage: _removeImage } = useImageUpload(uploadTriggerImage, deleteTriggerImage)
function onImageSelected(event: Event) { _onImageSelected(event, trigger.value.id, (url) => { trigger.value.image_url = url }) }
function removeImage() { _removeImage(trigger.value.id, () => { trigger.value.image_url = '' }) }

// Tabs
const activeTab = ref<'code' | 'connections'>('code')

// Fire output
const fireResult = ref('')
const firing = ref(false)

// Export modal
const showExportModal = ref(false)

// Pip
const pipInput = ref('')
const pipResults = ref<PipResult[]>([])

// AI Assist dialog
const showAiAssist = ref(false)
const aiAssistModel = ref('')
const aiAssistDescription = ref('')
const aiAssistLoading = ref(false)
const aiAssistStatus = ref('')
const aiAssistStreamJson = ref('')
const aiAssistResult = ref<Record<string, any> | null>(null)
const aiAssistAbort = ref<(() => void) | null>(null)
const aiAssistUsage = ref<{ input_tokens: number; output_tokens: number; cost: number } | null>(null)

const isCron = computed(() => trigger.value.trigger_type === TriggerType.Cron)
const isFileWatcher = computed(() => trigger.value.trigger_type === TriggerType.FileWatcher)
const isRSS = computed(() => trigger.value.trigger_type === TriggerType.RSS)
const isWebhook = computed(() => trigger.value.trigger_type === TriggerType.Webhook)
const isCustom = computed(() => trigger.value.trigger_type === TriggerType.Custom)
const webhookUrl = computed(() => {
  if (!isWebhook.value) return ''
  const origin = window.location.origin
  return `${origin}/api/triggers/${trigger.value.id}/webhook`
})

const contextHint = computed(() => {
  const base = 'trigger_type, trigger_name, trigger_time'
  switch (trigger.value.trigger_type) {
    case TriggerType.FileWatcher:
      return `${base}, file_path, file_name, event_type`
    case TriggerType.Webhook:
      return `${base}, webhook_body, webhook_method, webhook_content_type, webhook_headers, body_*`
    case TriggerType.RSS:
      return `${base}, feed_url, entry_title, entry_link, entry_summary, entry_id, entry_published`
    default:
      return base
  }
})

const DEFAULT_CODE = `def on_trigger(context: dict) -> dict:
    """Called when the trigger fires. Return a dict of outputs."""
    print(f"Trigger fired: {context.get('trigger_name')}")
    return context
`

const CUSTOM_CODE = `def run(emit):
    """Long-lived function. Call emit(dict) to fire the trigger."""
    import time
    while True:
        emit({"message": "hello from custom trigger"})
        time.sleep(10)
`

// Watch trigger_type changes to swap code template
watch(() => trigger.value.trigger_type, (newType, oldType) => {
  if (newType === oldType) return
  const code = trigger.value.code.trim()
  // Only swap if code matches the default template (user hasn't customized)
  const isDefaultCode = code === DEFAULT_CODE.trim() || code === CUSTOM_CODE.trim() || !code
  if (isDefaultCode) {
    trigger.value.code = newType === TriggerType.Custom ? CUSTOM_CODE : DEFAULT_CODE
  }
})

const triggerTemplateVariables = computed(() => {
  const vars = ['trigger_type', 'trigger_name', 'trigger_time']
  switch (trigger.value.trigger_type) {
    case TriggerType.FileWatcher: vars.push('file_path', 'file_name', 'event_type'); break
    case TriggerType.Webhook: vars.push('webhook_body', 'webhook_method', 'webhook_content_type', 'webhook_headers'); break
    case TriggerType.RSS: vars.push('feed_url', 'entry_title', 'entry_link', 'entry_summary', 'entry_id', 'entry_published'); break
  }
  for (const out of trigger.value.outputs)
    if (out.name && !vars.includes(out.name)) vars.push(out.name)
  return vars
})

onMounted(async () => {
  loadModels()
  if (route.query.new) {
    trigger.value.id = props.id
  } else {
    loading.value = true
    const data = await getTrigger(props.id)
    if (data && !('error' in data)) trigger.value = data as AiTrigger
    loading.value = false
  }
  pipelines.value = (await getPipelines()).filter(p => !p.id.startsWith('__'))
})

const saving = ref(false)

async function save() {
  if (saving.value) return
  saving.value = true
  try {
    const result = await saveTrigger(trigger.value)
    // Clear ?new query param so refresh loads from DB
    if (route.query.new) {
      router.replace({ path: route.path, query: {} })
    }
    if (result.pip_results) {
      pipResults.value = result.pip_results
      const failed = result.pip_results.filter(r => !r.success)
      if (failed.length) {
        toast(`Trigger saved. ${failed.length} pip install(s) failed`, 'error')
      } else {
        toast(`Trigger saved. ${result.pip_results.length} package(s) installed`, 'success')
      }
    } else {
      pipResults.value = []
      toast('Trigger saved', 'success')
    }
  } catch (e: any) {
    toast(e.message || 'Failed to save trigger', 'error')
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!confirm('Delete this trigger?')) return
  await deleteTrigger(trigger.value.id)
  router.push('/triggers')
}

async function fire() {
  firing.value = true
  fireResult.value = ''
  try {
    const result = await fireTrigger(trigger.value.id)
    fireResult.value = JSON.stringify(result, null, 2)
    // Refresh to get updated fire count
    const data = await getTrigger(props.id)
    if (data && !('error' in data)) {
      trigger.value.fire_count = (data as AiTrigger).fire_count
      trigger.value.last_fired_at = (data as AiTrigger).last_fired_at
      trigger.value.last_status = (data as AiTrigger).last_status
    }
  } catch (e: any) {
    fireResult.value = `Error: ${e.message}`
  }
  firing.value = false
}

function exportTrigger() {
  showExportModal.value = true
}

async function onExportConfirm(exportName: string, exportDescription: string, version: number) {
  if (!trigger.value.export_uid) trigger.value.export_uid = getUid()
  trigger.value.export_version = version
  await saveTrigger(trigger.value)

  const data: any = deepClone(trigger.value)
  delete data.id
  delete data.created_at
  delete data.updated_at
  // Convert image URL to base64 for portability
  if (data.image_url) {
    data.image_url = await imageUrlToBase64(data.image_url) || ''
  }
  data._export_type = 'trigger'
  data._export_name = exportName
  data._export_description = exportDescription
  data._export_date = new Date().toISOString()
  data._pip_packages = trigger.value.pip_dependencies || []
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${exportName || 'trigger'}.json`
  a.click()
  URL.revokeObjectURL(url)
}

// Outputs
function addOutput() {
  trigger.value.outputs.push({ name: '', value: '', type: PropertyType.TEXT })
}
function removeOutput(idx: number) {
  trigger.value.outputs.splice(idx, 1)
}

// Pip dependencies
function addPipDep() {
  const pkg = pipInput.value.trim()
  if (pkg && !trigger.value.pip_dependencies.includes(pkg)) {
    trigger.value.pip_dependencies.push(pkg)
  }
  pipInput.value = ''
}
function removePipDep(idx: number) {
  trigger.value.pip_dependencies.splice(idx, 1)
}

// Env variables
function addEnvVar() {
  trigger.value.env_variables.push({ name: '', description: '', type: PropertyType.TEXT })
}
function removeEnvVar(idx: number) {
  trigger.value.env_variables.splice(idx, 1)
}

// Inline env var value editing
const showEnvValues = ref(false)
const envVarValues = ref<Record<string, string>>({})
const envVarSaving = ref(false)

async function loadEnvVarValues() {
  const groups = await getCustomSettings()
  const group = groups.find(g => g.resource_type === 'trigger' && g.resource_id === trigger.value.id)
  const vals: Record<string, string> = {}
  if (group) {
    for (const v of group.variables) vals[v.name] = v.value
  }
  for (const v of trigger.value.env_variables) {
    if (v.name && !(v.name in vals)) vals[v.name] = ''
  }
  envVarValues.value = vals
  showEnvValues.value = true
}

async function saveEnvVarValues() {
  envVarSaving.value = true
  const items = Object.entries(envVarValues.value)
    .filter(([name]) => name.trim())
    .map(([name, value]) => ({
      resource_type: 'trigger',
      resource_id: trigger.value.id,
      name,
      value,
    }))
  await saveCustomSettings(items)
  envVarSaving.value = false
  toast('Env variable values saved', 'success')
}

// Connections
function addConnection() {
  trigger.value.connections.push({
    id: getUid(),
    pipeline_id: '',
    pipeline_name: '',
    is_enabled: true,
    input_mappings: [],
  })
}

function removeConnection(idx: number) {
  trigger.value.connections.splice(idx, 1)
}

async function onPipelineSelected(conn: TriggerConnection) {
  if (!conn.pipeline_id) {
    conn.pipeline_name = ''
    conn.input_mappings = []
    return
  }
  const pipeline = await getPipeline(conn.pipeline_id)
  if (!pipeline) return
  conn.pipeline_name = pipeline.name
  // Auto-populate input mappings from pipeline inputs
  conn.input_mappings = (pipeline.inputs || []).map(inp => ({
    pipeline_input: inp.name,
    expression: '',
  }))
}

function addMapping(conn: TriggerConnection) {
  conn.input_mappings.push({ pipeline_input: '', expression: '' })
}

function removeMapping(conn: TriggerConnection, idx: number) {
  conn.input_mappings.splice(idx, 1)
}

function copyWebhookUrl() {
  navigator.clipboard.writeText(webhookUrl.value)
  toast('Copied!', 'success')
}

// AI Assist
function openAiAssist() {
  aiAssistStatus.value = ''
  aiAssistStreamJson.value = ''
  aiAssistResult.value = null
  aiAssistUsage.value = null
  showAiAssist.value = true
}

function closeAiAssist() {
  if (aiAssistAbort.value) aiAssistAbort.value()
  aiAssistLoading.value = false
  showAiAssist.value = false
}

async function generateWithAi() {
  if (aiAssistLoading.value || !aiAssistDescription.value.trim()) return
  aiAssistLoading.value = true
  aiAssistStatus.value = 'Connecting...'
  aiAssistStreamJson.value = ''
  aiAssistResult.value = null

  const { promise, abort } = wsAiAssistTrigger(
    aiAssistDescription.value,
    aiAssistModel.value,
    trigger.value,
    (event: TriggerAiAssistEvent) => {
      if (event.type === 'status') {
        aiAssistStatus.value = event.text || ''
      } else if (event.type === 'delta') {
        aiAssistStreamJson.value += event.text || ''
      } else if (event.type === 'result') {
        aiAssistResult.value = event.trigger_config || null
        if (event.usage) {
          const u = event.usage
          const m = models.value.find((m: any) => m.id === u.model)
          const inCost = m ? ((u.input_tokens || 0) / 1_000_000) * m.input_cost : 0
          const outCost = m ? ((u.output_tokens || 0) / 1_000_000) * m.output_cost : 0
          aiAssistUsage.value = { input_tokens: u.input_tokens || 0, output_tokens: u.output_tokens || 0, cost: inCost + outCost }
        }
        aiAssistStatus.value = 'Done'
        aiAssistLoading.value = false
      } else if (event.type === 'error') {
        aiAssistStatus.value = ''
        aiAssistLoading.value = false
        toast(event.text || 'AI assist failed', 'error')
      }
    },
  )
  aiAssistAbort.value = abort

  try {
    await promise
  } catch {
    if (aiAssistLoading.value) {
      aiAssistStatus.value = ''
      aiAssistLoading.value = false
      toast('AI assist connection failed', 'error')
    }
  }
}

function applyAiResult() {
  if (!aiAssistResult.value) return
  const config = aiAssistResult.value

  // Basic fields
  if (config.name) trigger.value.name = config.name
  if (config.description) trigger.value.description = config.description
  if (config.tag) trigger.value.tag = config.tag
  if (config.trigger_type !== undefined) trigger.value.trigger_type = config.trigger_type

  // Type-specific config
  if (config.cron_expression !== undefined) trigger.value.cron_expression = config.cron_expression
  if (config.watch_path !== undefined) trigger.value.watch_path = config.watch_path
  if (config.watch_patterns !== undefined) trigger.value.watch_patterns = config.watch_patterns
  if (Array.isArray(config.watch_events)) trigger.value.watch_events = config.watch_events
  if (config.rss_url !== undefined) trigger.value.rss_url = config.rss_url
  if (config.rss_poll_minutes !== undefined) trigger.value.rss_poll_minutes = config.rss_poll_minutes

  // Code
  if (config.code) trigger.value.code = config.code

  // Outputs
  if (Array.isArray(config.outputs) && config.outputs.length) {
    trigger.value.outputs = config.outputs.map((o: any) => ({
      name: o.name || '',
      value: '',
      type: o.type ?? PropertyType.TEXT,
    }))
  }

  // Pip dependencies
  if (Array.isArray(config.pip_dependencies)) {
    trigger.value.pip_dependencies = config.pip_dependencies
  }

  // Env variables
  if (Array.isArray(config.env_variables) && config.env_variables.length) {
    trigger.value.env_variables = config.env_variables.map((v: any) => ({
      name: v.name || '',
      description: v.description || '',
      type: v.type ?? PropertyType.TEXT,
    }))
  }

  // Connections
  if (Array.isArray(config.connections) && config.connections.length) {
    trigger.value.connections = config.connections.map((c: any) => ({
      id: getUid(),
      pipeline_id: c.pipeline_id || '',
      pipeline_name: c.pipeline_name || '',
      is_enabled: c.is_enabled ?? true,
      input_mappings: Array.isArray(c.input_mappings) ? c.input_mappings.map((m: any) => ({
        pipeline_input: m.pipeline_input || '',
        expression: m.expression || '',
      })) : [],
    }))
  }

  toast('AI trigger configuration applied', 'success')
  showAiAssist.value = false
}
</script>

<template>
  <div class="flex h-full">
    <!-- Left Sidebar -->
    <div class="w-72 bg-gray-900 border-r border-gray-800 flex flex-col">
      <!-- Header -->
      <div class="p-4 border-b border-gray-800">
        <div class="flex items-center gap-3">
          <button @click="router.push('/triggers')" class="text-gray-400 hover:text-gray-50 text-sm">&larr;</button>
          <h1 class="text-lg font-bold truncate">{{ route.query.new ? 'New Trigger' : trigger.name || 'Edit Trigger' }}</h1>
        </div>
      </div>

      <!-- AI Assist button -->
      <div class="px-4 py-2 border-b border-gray-800">
        <button
          @click="openAiAssist"
          class="w-full flex items-center justify-center gap-2 px-3 py-2 bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 rounded-lg text-sm font-medium text-purple-400 transition-colors"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
          AI Assist
        </button>
      </div>

      <!-- Scrollable content -->
      <div class="flex-1 overflow-y-auto min-h-0">

      <div v-if="loading" class="p-4 text-gray-400 text-sm">Loading...</div>

      <template v-else>
        <!-- Settings -->
        <div class="p-4 border-b border-gray-800 space-y-3">
          <div class="text-xs text-gray-500 uppercase font-medium">Settings</div>

          <div>
            <label class="block text-xs text-gray-400 mb-1">Name</label>
            <input v-model="trigger.name" class="input-sm" />
          </div>

          <div>
            <label class="block text-xs text-gray-400 mb-1">Type</label>
            <select v-model.number="trigger.trigger_type" class="input-sm">
              <option :value="TriggerType.Cron">Cron</option>
              <option :value="TriggerType.FileWatcher">File Watcher</option>
              <option :value="TriggerType.Webhook">Webhook</option>
              <option :value="TriggerType.RSS">RSS</option>
              <option :value="TriggerType.Custom">Custom</option>
            </select>
          </div>

          <div class="flex items-center gap-2">
            <label class="text-xs text-gray-400">Enabled</label>
            <input type="checkbox" v-model="trigger.is_enabled" />
          </div>

          <!-- Trigger Image -->
          <div>
            <label class="block text-xs text-gray-400 mb-1">Image</label>
            <div class="flex items-center gap-3">
              <div v-if="trigger.image_url" class="relative group">
                <img :src="trigger.image_url" class="w-16 h-16 rounded-lg object-cover border border-gray-700 bg-black" />
                <button @click="removeImage" class="absolute -top-1.5 -right-1.5 w-5 h-5 bg-red-600 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity" title="Remove image">x</button>
              </div>
              <LetterAvatar v-else :letter="trigger.name" :size="64" />
              <button @click="imageFileInput?.click()" :disabled="uploadingImage" class="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs text-gray-300 transition-colors disabled:opacity-50">
                {{ uploadingImage ? 'Uploading...' : 'Upload' }}
              </button>
              <input ref="imageFileInput" type="file" accept="image/*" class="hidden" @change="onImageSelected" />
            </div>
          </div>

          <div>
            <label class="block text-xs text-gray-400 mb-1">Description</label>
            <input v-model="trigger.description" class="input-sm" />
          </div>

          <div>
            <label class="block text-xs text-gray-400 mb-1">Tag</label>
            <input v-model="trigger.tag" class="input-sm" />
          </div>
        </div>

        <!-- Type-specific config -->
        <div class="p-4 border-b border-gray-800 space-y-3">
          <div class="text-xs text-gray-500 uppercase font-medium">{{ TriggerTypeLabels[trigger.trigger_type as TriggerType] }} Config</div>

          <!-- Cron -->
          <template v-if="isCron">
            <div>
              <label class="block text-xs text-gray-400 mb-1">Cron Expression</label>
              <input v-model="trigger.cron_expression" placeholder="0 * * * *" class="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm font-mono focus:outline-none focus:border-blue-500" />
              <p class="text-xs text-gray-600 mt-1">min hour day month weekday</p>
            </div>
          </template>

          <!-- File Watcher -->
          <template v-if="isFileWatcher">
            <div>
              <label class="block text-xs text-gray-400 mb-1">Watch Path</label>
              <input v-model="trigger.watch_path" placeholder="/path/to/watch" class="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm font-mono focus:outline-none focus:border-blue-500" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">File Patterns</label>
              <input v-model="trigger.watch_patterns" placeholder="*.csv,*.json" class="input-sm" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">Events</label>
              <div class="flex gap-3">
                <label v-for="evt in ['created', 'modified', 'deleted']" :key="evt" class="flex items-center gap-1 text-xs text-gray-300">
                  <input type="checkbox" :checked="trigger.watch_events.includes(evt)" @change="trigger.watch_events.includes(evt) ? trigger.watch_events.splice(trigger.watch_events.indexOf(evt), 1) : trigger.watch_events.push(evt)" />
                  {{ evt }}
                </label>
              </div>
            </div>
          </template>

          <!-- RSS -->
          <template v-if="isRSS">
            <div>
              <label class="block text-xs text-gray-400 mb-1">Feed URL</label>
              <input v-model="trigger.rss_url" placeholder="https://example.com/feed.xml" class="input-sm" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">Poll Interval (minutes)</label>
              <input v-model.number="trigger.rss_poll_minutes" type="number" min="1" class="input-sm" />
            </div>
          </template>

          <!-- Webhook -->
          <template v-if="isWebhook">
            <div>
              <label class="block text-xs text-gray-400 mb-1">Webhook URL</label>
              <div class="flex gap-1">
                <input :value="webhookUrl" readonly class="flex-1 px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-xs font-mono text-gray-300 focus:outline-none" />
                <button @click="copyWebhookUrl" class="px-2 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs transition-colors" title="Copy URL">
                  Copy
                </button>
              </div>
              <p class="text-xs text-gray-600 mt-1">POST to this URL to fire the trigger.</p>
            </div>
          </template>

          <!-- Custom -->
          <template v-if="isCustom">
            <div class="p-2 bg-cyan-900/20 border border-cyan-800/30 rounded text-xs text-cyan-300 space-y-1">
              <p class="font-medium">Long-lived subprocess</p>
              <p class="text-cyan-400/80">Write a <code class="bg-cyan-900/40 px-1 rounded">run(emit)</code> function that runs continuously. Call <code class="bg-cyan-900/40 px-1 rounded">emit(dict)</code> to fire the trigger and run connected pipelines.</p>
              <p class="text-cyan-400/80">The subprocess starts when the trigger is enabled and stops when disabled or deleted.</p>
            </div>
          </template>
        </div>

        <!-- Outputs -->
        <div class="p-4 border-b border-gray-800">
          <div class="flex items-center justify-between mb-2">
            <div class="text-xs text-gray-500 uppercase font-medium">Outputs</div>
            <button @click="addOutput" class="text-xs text-blue-400 hover:text-blue-300">+ Add</button>
          </div>
          <div class="space-y-1">
            <div v-for="(out, idx) in trigger.outputs" :key="idx" class="flex items-center gap-1">
              <input v-model="out.name" placeholder="Name" class="flex-1 px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" />
              <select v-model.number="out.type" class="px-1 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500">
                <option :value="0">Text</option>
                <option :value="1">Number</option>
                <option :value="2">Boolean</option>
              </select>
              <button @click="removeOutput(idx)" class="text-red-400 hover:text-red-300 text-xs">&times;</button>
            </div>
          </div>
          <p v-if="trigger.outputs.length === 0" class="text-xs text-gray-600 mt-1">No outputs defined. Context vars are available by default.</p>
        </div>

        <!-- Pip Dependencies -->
        <div class="p-4 border-b border-gray-800">
          <label class="block text-xs text-gray-500 uppercase font-medium mb-2">Pip Dependencies</label>
          <div class="flex gap-1 mb-1">
            <input v-model="pipInput" @keydown.enter.prevent="addPipDep" placeholder="package name" class="flex-1 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" />
            <button @click="addPipDep" class="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs">+</button>
          </div>
          <div class="flex flex-wrap gap-1">
            <span v-for="(pkg, idx) in trigger.pip_dependencies" :key="idx" class="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-800 border border-gray-700 rounded text-xs">
              {{ pkg }}
              <button @click="removePipDep(idx)" class="text-red-400 hover:text-red-300 ml-0.5">&times;</button>
            </span>
          </div>
          <div v-if="pipResults.length" class="mt-1 space-y-0.5">
            <div v-for="r in pipResults" :key="r.package" class="text-xs" :class="r.success ? 'text-green-400' : 'text-red-400'">
              {{ r.package }}: {{ r.success ? 'installed' : r.error }}
            </div>
          </div>
        </div>

        <!-- Env Variables -->
        <div class="p-4">
          <div class="flex items-center justify-between mb-2">
            <label class="block text-xs text-gray-500 uppercase font-medium">Env Variables</label>
            <button @click="addEnvVar" class="text-xs text-blue-400 hover:text-blue-300">+ Add</button>
          </div>
          <div class="space-y-1">
            <div v-for="(v, idx) in trigger.env_variables" :key="idx" class="p-1.5 bg-gray-800/50 rounded border border-gray-800 space-y-1">
              <div class="flex items-center gap-1">
                <input v-model="v.name" placeholder="VAR_NAME" class="flex-1 px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500" />
                <select v-model.number="v.type" class="px-1 py-0.5 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500">
                  <option :value="0">Text</option>
                  <option :value="5">Secret</option>
                </select>
                <button @click="removeEnvVar(idx)" class="text-red-400 hover:text-red-300 text-xs">&times;</button>
              </div>
              <input v-model="v.description" placeholder="Description" class="w-full px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" />
            </div>
          </div>
          <div v-if="trigger.env_variables.length && trigger.id" class="mt-2">
            <button v-if="!showEnvValues" @click="loadEnvVarValues" class="text-xs text-blue-400 hover:text-blue-300 transition-colors">Set Values</button>
            <div v-else class="p-2 bg-gray-800/70 rounded border border-gray-700 space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="text-xs text-gray-400 font-medium">Variable Values</span>
                <button @click="showEnvValues = false" class="text-xs text-gray-500 hover:text-gray-300">&times;</button>
              </div>
              <div v-for="v in trigger.env_variables" :key="v.name" class="space-y-0.5">
                <label class="text-xs text-gray-500 font-mono">{{ v.name }}</label>
                <input
                  v-if="v.type !== PropertyType.PASSWORD"
                  v-model="envVarValues[v.name]"
                  :placeholder="v.description || v.name"
                  class="w-full px-1.5 py-0.5 bg-gray-900 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500"
                />
                <input
                  v-else
                  v-model="envVarValues[v.name]"
                  type="password"
                  :placeholder="envVarValues[v.name] ? '••••••••' : v.description || v.name"
                  class="w-full px-1.5 py-0.5 bg-gray-900 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500"
                />
              </div>
              <button @click="saveEnvVarValues" :disabled="envVarSaving" class="w-full px-2 py-1 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded text-xs font-medium transition-colors">
                {{ envVarSaving ? 'Saving...' : 'Save Values' }}
              </button>
            </div>
          </div>
          <p v-if="trigger.env_variables.length && !trigger.id" class="text-xs text-gray-600 mt-1">Save the trigger first to set variable values.</p>
          <p v-if="trigger.env_variables.length" class="text-xs text-gray-600 mt-1">In code, use get_var("VAR_NAME") or os.getenv("VAR_NAME").</p>
        </div>
      </template>
      </div><!-- /scrollable -->

      <!-- Actions -->
      <div class="p-3 border-t border-gray-800 space-y-2">
        <button v-if="auth.canEdit('triggers')" @click="save" :disabled="saving" class="w-full px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors">
          {{ saving ? 'Saving...' : 'Save' }}
        </button>
        <button v-if="!isCustom" @click="fire" :disabled="firing" class="w-full px-3 py-2 bg-green-600 hover:bg-green-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors">
          {{ firing ? 'Firing...' : 'Fire' }}
        </button>
        <div class="flex gap-2">
          <button @click="exportTrigger" class="flex-1 px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition-colors">
            Export
          </button>
          <button v-if="auth.canDelete('triggers')" @click="remove" class="flex-1 px-3 py-2 bg-red-900/40 hover:bg-red-900/60 text-red-400 rounded-lg text-sm font-medium transition-colors">
            Delete
          </button>
        </div>
      </div>
    </div>

    <!-- Middle: Code / Connections -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <!-- Tabs -->
      <div class="flex border-b border-gray-800">
        <button
          @click="activeTab = 'code'"
          class="px-4 py-2 text-sm font-medium transition-colors"
          :class="activeTab === 'code' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-500 hover:text-gray-300'"
        >
          Code
        </button>
        <button
          @click="activeTab = 'connections'"
          class="px-4 py-2 text-sm font-medium transition-colors"
          :class="activeTab === 'connections' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-gray-500 hover:text-gray-300'"
        >
          Connections ({{ trigger.connections.length }})
        </button>
      </div>

      <!-- Code tab -->
      <div v-if="activeTab === 'code'" class="flex-1 flex flex-col overflow-hidden">
        <div class="p-3 border-b border-gray-800">
          <p v-if="isCustom" class="text-xs text-gray-500">
            <span v-pre>Python function: def run(emit). Call emit(dict) to fire the trigger. Use {{ key }} in connection mappings.</span>
            <br />The emitted dict keys become available as template variables in connections.
          </p>
          <p v-else class="text-xs text-gray-500">
            <span v-pre>Python function: def on_trigger(context: dict) -> dict. Use {{ key }} in connection mappings.</span>
            <br />Context keys: <code class="text-gray-400">{{ contextHint }}</code>
          </p>
        </div>
        <div class="flex-1 overflow-hidden p-3">
          <CodeEditor v-model="trigger.code" language="python" height="100%" :fileUri="`file:///workspace/trigger_${trigger.id}.py`" />
        </div>
      </div>

      <!-- Connections tab -->
      <div v-if="activeTab === 'connections'" class="flex-1 overflow-auto p-4 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-bold text-gray-300">Pipeline Connections</h3>
          <button @click="addConnection" class="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs font-medium transition-colors">
            + Add Connection
          </button>
        </div>

        <div v-if="trigger.connections.length === 0" class="text-gray-500 text-sm text-center py-8">
          No connections yet. Add a connection to link this trigger to a pipeline.
        </div>

        <div
          v-for="(conn, connIdx) in trigger.connections"
          :key="conn.id"
          class="bg-gray-800/50 border border-gray-700 rounded-lg p-4 space-y-3"
        >
          <div class="flex items-center gap-3">
            <select
              v-model="conn.pipeline_id"
              @change="onPipelineSelected(conn)"
              class="flex-1 px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm focus:outline-none focus:border-blue-500"
            >
              <option value="">Select pipeline...</option>
              <option v-for="p in pipelines" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
            <label class="flex items-center gap-1 text-xs text-gray-400">
              <input type="checkbox" v-model="conn.is_enabled" /> Enabled
            </label>
            <button @click="removeConnection(connIdx)" class="text-red-400 hover:text-red-300 text-sm">&times;</button>
          </div>

          <div v-if="conn.pipeline_id" class="space-y-2">
            <div class="flex items-center justify-between">
              <div class="text-xs text-gray-500 uppercase font-medium">Input Mappings</div>
              <button @click="addMapping(conn)" class="text-xs text-blue-400 hover:text-blue-300">+ Add</button>
            </div>
            <div v-for="(mapping, mapIdx) in conn.input_mappings" :key="mapIdx" class="flex items-center gap-2">
              <input
                v-model="mapping.pipeline_input"
                placeholder="Pipeline input"
                class="w-40 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500"
                readonly
              />
              <span class="text-gray-600 text-xs">&#8592;</span>
              <TemplateInput
                v-model="mapping.expression"
                :variables="triggerTemplateVariables"
                mode="input"
                placeholder="{{trigger_time}}"
                inputClass="flex-1 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500"
                class="flex-1"
              />
              <button @click="removeMapping(conn, mapIdx)" class="text-red-400 hover:text-red-300 text-xs">&times;</button>
            </div>
            <p v-if="conn.input_mappings.length === 0" class="text-xs text-gray-600">No inputs defined for this pipeline.</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Right: Fire output -->
    <div class="w-80 bg-gray-900 border-l border-gray-800 flex flex-col">
      <div class="p-3 border-b border-gray-800 text-sm font-medium text-gray-400">Fire Output</div>
      <div class="p-3 border-b border-gray-800 space-y-1 text-xs text-gray-500">
        <div class="flex items-center gap-2">
          <span class="w-1.5 h-1.5 rounded-full" :class="trigger.is_enabled ? 'bg-green-400' : 'bg-gray-600'"></span>
          {{ trigger.is_enabled ? 'Enabled' : 'Disabled' }}
        </div>
        <div v-if="trigger.fire_count">Fires: {{ trigger.fire_count }}</div>
        <div v-if="trigger.last_fired_at">Last: {{ new Date(trigger.last_fired_at).toLocaleString() }}</div>
        <div v-if="trigger.last_status">
          Status: <span :class="trigger.last_status === 'OK' ? 'text-green-400' : 'text-red-400'">{{ trigger.last_status }}</span>
        </div>
      </div>
      <div class="flex-1 overflow-auto p-4">
        <pre v-if="fireResult" class="text-sm text-gray-300 whitespace-pre-wrap font-mono">{{ fireResult }}</pre>
        <div v-else class="text-gray-600 text-sm">Fire the trigger to see output here</div>
      </div>
    </div>

    <!-- AI Assist Dialog -->
    <Teleport to="body">
      <div v-if="showAiAssist" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/60" @click="closeAiAssist"></div>
        <div class="relative bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-[640px] max-h-[80vh] flex flex-col">
          <!-- Dialog header -->
          <div class="flex items-center justify-between px-5 py-4 border-b border-gray-800">
            <div class="flex items-center gap-2">
              <svg class="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
              <h2 class="text-lg font-bold text-gray-100">AI Assist</h2>
            </div>
            <button @click="closeAiAssist" class="text-gray-500 hover:text-gray-300 transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          </div>

          <!-- Dialog body -->
          <div class="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            <!-- Model selector -->
            <div>
              <label class="block text-xs text-gray-400 mb-1">Model</label>
              <ModelSelectDropdown v-model="aiAssistModel" :models="models" />
            </div>

            <!-- Description -->
            <div>
              <label class="block text-xs text-gray-400 mb-1">Describe what you want this trigger to do</label>
              <textarea
                v-model="aiAssistDescription"
                rows="3"
                placeholder="e.g. Create a cron trigger that runs every morning at 9am and sends a summary to my Daily Report pipeline..."
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-purple-500 resize-y"
                :disabled="aiAssistLoading"
                @keydown.ctrl.enter="generateWithAi"
              ></textarea>
            </div>

            <!-- Streaming output area -->
            <div v-if="aiAssistStatus || aiAssistStreamJson" class="space-y-2">
              <!-- Status indicator -->
              <div v-if="aiAssistLoading" class="flex items-center gap-2 text-sm text-purple-300">
                <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                {{ aiAssistStatus }}
              </div>
              <div v-else-if="aiAssistStatus === 'Done'" class="flex items-center gap-2 text-sm text-green-400">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
                Generation complete
                <span v-if="aiAssistUsage" class="text-xs text-gray-500 ml-2">
                  {{ aiAssistUsage.input_tokens.toLocaleString() }} in / {{ aiAssistUsage.output_tokens.toLocaleString() }} out
                  <span v-if="aiAssistUsage.cost"> &middot; ${{ aiAssistUsage.cost.toFixed(4) }}</span>
                </span>
              </div>

              <!-- Streaming JSON display -->
              <div v-if="aiAssistStreamJson" class="relative">
                <div class="text-xs text-gray-500 mb-1">Generated Configuration</div>
                <pre class="bg-gray-950 border border-gray-800 rounded-lg p-3 text-xs text-gray-300 font-mono overflow-auto max-h-64 whitespace-pre-wrap">{{ aiAssistStreamJson }}</pre>
              </div>
            </div>
          </div>

          <!-- Dialog footer -->
          <div class="px-5 py-3 border-t border-gray-800 flex items-center gap-2 justify-end">
            <button
              @click="closeAiAssist"
              class="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
            >
              Cancel
            </button>
            <button
              v-if="aiAssistResult"
              @click="applyAiResult"
              class="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-medium transition-colors"
            >
              Apply to Trigger
            </button>
            <button
              v-else
              @click="generateWithAi"
              :disabled="aiAssistLoading || !aiAssistDescription.trim()"
              class="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition-colors"
            >
              {{ aiAssistLoading ? 'Generating...' : 'Generate' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <ExportModal
      v-model="showExportModal"
      :defaultName="trigger.name"
      :defaultDescription="trigger.description"
      :defaultVersion="trigger.export_version || 1"
      @confirm="onExportConfirm"
    />
  </div>
</template>
