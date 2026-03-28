<script setup lang="ts">
import { ref, onMounted, computed, watch, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { getTool, saveTool, testMcpConnection, getToolRuns, deleteToolRun, wsAiAssistTool, uploadToolImage, deleteToolImage } from '@/services/toolService'
import { useImageUpload } from '@/composables/useImageUpload'
import type { AiAssistEvent } from '@/services/toolService'
import { createTool, ToolType, EndpointMethod, PropertyType, McpTransport, getUid, PipelineStatusType, StatusLabels, StatusColors, type AiTool, type AiPipelineRun, type AgentFunction, type EnvVariable, type McpServer, type CustomSettingsGroup } from '@/models'
import { parseKv, serializeKv } from '@/utils/kv'
import { deepClone } from '@/utils/clone'
import type { PipResult } from '@/services/toolService'
import { useModels, loadModels } from '@/composables/useModels'
import ModelSelectDropdown from '@/components/shared/ModelSelectDropdown.vue'
import DynamicInput from '@/components/shared/DynamicInput.vue'
import InputConfigModal from '@/components/shared/InputConfigModal.vue'
import TemplateInput from '@/components/shared/TemplateInput.vue'
import KeyValueEditor from '@/components/shared/KeyValueEditor.vue'
import ResponseStructureEditor from '@/components/shared/ResponseStructureEditor.vue'
import CodeEditor from '@/components/CodeEditor.vue'
import ExportModal from '@/components/shared/ExportModal.vue'
import LetterAvatar from '@/components/shared/LetterAvatar.vue'
import { getCustomSettings, saveCustomSettings } from '@/services/settingsService'
import { imageUrlToBase64 } from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useAuth } from '@/composables/useAuth'
const { show: toast } = useToast()
const auth = useAuth()

const { models } = useModels()

const props = defineProps<{ id: string }>()
const router = useRouter()
const route = useRoute()

const tool = ref<AiTool>(createTool())
const loading = ref(false)

const selectedFunction = ref<AgentFunction | null>(null)
const showInputConfig = ref(false)
const configInput = ref<any>(null)
const showExportModal = ref(false)

const { imageFileInput, uploadingImage, onImageSelected: _onImageSelected, removeImage: _removeImage } = useImageUpload(uploadToolImage, deleteToolImage)
function onImageSelected(event: Event) { _onImageSelected(event, tool.value.id, (url) => { tool.value.image_url = url }) }
function removeImage() { _removeImage(tool.value.id, () => { tool.value.image_url = '' }) }

const pipInput = ref('')
const pipResults = ref<PipResult[]>([])
const toolRuns = ref<AiPipelineRun[]>([])
const showRunHistory = ref(false)
const testing = ref(false)

const showAiAssist = ref(false)
const aiAssistModel = ref('')
const aiAssistDescription = ref('')
const aiAssistLoading = ref(false)
const aiAssistStatus = ref('')
const aiAssistStreamJson = ref('')
const aiAssistResult = ref<Record<string, any> | null>(null)
const aiAssistAbort = ref<(() => void) | null>(null)
const aiAssistUsage = ref<{ input_tokens: number; output_tokens: number; cost: number } | null>(null)

const isLLM = computed(() => tool.value.type === ToolType.LLM)
const isEndpoint = computed(() => tool.value.type === ToolType.Endpoint)
const isAgent = computed(() => tool.value.type === ToolType.Agent)

const templateVariables = computed(() =>
  tool.value.request_inputs.map(inp => inp.name).filter(Boolean)
)

const endpointHasBody = computed(() =>
  tool.value.endpoint_method === EndpointMethod.POST || tool.value.endpoint_method === EndpointMethod.PUT
)

const endpointHeaders = ref<{ key: string; value: string }[]>([])
const endpointBody = ref<{ key: string; value: string }[]>([])
const endpointQuery = ref<{ key: string; value: string }[]>([])


function loadKvFields() {
  endpointHeaders.value = parseKv(tool.value.endpoint_headers)
  endpointBody.value = parseKv(tool.value.endpoint_body)
  endpointQuery.value = parseKv(tool.value.endpoint_query)
}

function syncKvToTool() {
  tool.value.endpoint_headers = serializeKv(endpointHeaders.value)
  tool.value.endpoint_body = serializeKv(endpointBody.value)
  tool.value.endpoint_query = serializeKv(endpointQuery.value)
}

watch(endpointHeaders, syncKvToTool, { deep: true })
watch(endpointBody, syncKvToTool, { deep: true })
watch(endpointQuery, syncKvToTool, { deep: true })

onMounted(async () => {
  if (route.query.new) {
    tool.value.id = props.id
  } else {
    loading.value = true
    const data = await getTool(props.id)
    if (data && !('error' in data)) tool.value = data as AiTool
    loading.value = false
  }
  if (!tool.value.response_structure) tool.value.response_structure = []
  for (const srv of (tool.value.mcp_servers || [])) {
    if (!srv.headers) srv.headers = []
  }
  loadKvFields()
  await loadModels()
  try { toolRuns.value = await getToolRuns(props.id) } catch {}
})

const saving = ref(false)

async function save() {
  if (saving.value) return
  saving.value = true
  try {

    const saved = deepClone(tool.value)
    saved.request_inputs.forEach((inp: any) => { inp.value = '' })
    const result = await saveTool(saved)
    if (result.pip_results) {
      pipResults.value = result.pip_results
      const failed = result.pip_results.filter(r => !r.success)
      if (failed.length) {
        toast(`Tool saved. ${failed.length} pip install(s) failed`, 'error')
      } else {
        toast(`Tool saved. ${result.pip_results.length} package(s) installed`, 'success')
      }
    } else {
      pipResults.value = []
      toast('Tool saved', 'success')
    }
  } catch (e: any) {
    toast(e.message || 'Failed to save tool', 'error')
  } finally {
    saving.value = false
  }
}

async function deleteTool() {
  if (!confirm('Are you sure you want to delete this tool?')) return
  const { del } = await import('@/services/api')
  await del(`/api/tools/${tool.value.id}`)
  router.push('/tools')
}

async function test() {
  testing.value = true
  try {
    // Save first so the backend has the latest tool config
    const saved = deepClone(tool.value)
    saved.request_inputs.forEach((inp: any) => { inp.value = '' })
    await saveTool(saved)
    router.push(`/tool-runner/${tool.value.id}`)
  } catch (e: any) {
    toast(e.message || 'Failed to save tool', 'error')
    testing.value = false
  }
}

async function deleteRun(runId: string) {
  await deleteToolRun(runId)
  toolRuns.value = toolRuns.value.filter(r => r.id !== runId)
}

const statusLabels = StatusLabels
const statusColors = StatusColors


function addInput() {
  tool.value.request_inputs.push({ name: '', value: '', type: PropertyType.TEXT, is_required: false, is_default: false })
}
function removeInput(idx: number) {
  tool.value.request_inputs.splice(idx, 1)
}


function addPipDep() {
  const pkg = pipInput.value.trim()
  if (pkg && !tool.value.pip_dependencies.includes(pkg)) {
    tool.value.pip_dependencies.push(pkg)
  }
  pipInput.value = ''
}
function removePipDep(idx: number) {
  tool.value.pip_dependencies.splice(idx, 1)
}

// Env variable management
function addEnvVar() {
  tool.value.env_variables.push({ name: '', description: '', type: PropertyType.TEXT })
}
function removeEnvVar(idx: number) {
  tool.value.env_variables.splice(idx, 1)
}

// Inline env var value editing
const showEnvValues = ref(false)
const envVarValues = ref<Record<string, string>>({})
const envVarSaving = ref(false)

async function loadEnvVarValues() {
  const groups = await getCustomSettings()
  const group = groups.find(g => g.resource_type === 'tool' && g.resource_id === tool.value.id)
  const vals: Record<string, string> = {}
  if (group) {
    for (const v of group.variables) vals[v.name] = v.value
  }
  // Ensure all declared vars have an entry
  for (const v of tool.value.env_variables) {
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
      resource_type: 'tool',
      resource_id: tool.value.id,
      name,
      value,
    }))
  await saveCustomSettings(items)
  envVarSaving.value = false
  toast('Env variable values saved', 'success')
}

// MCP server management
const mcpTestResults = ref<Record<string, { loading: boolean; result?: string; tools?: { name: string; description: string }[] }>>({})

function addMcpServer() {
  const uid = getUid(6)
  tool.value.mcp_servers.push({
    uid,
    name: `Server ${uid}`,
    transport: McpTransport.STDIO,
    command: '',
    args: [],
    url: '',
    headers: [],
    is_enabled: true,
    allowed_tools: [],
    discovered_tools: [],
  })
}

function removeMcpServer(idx: number) {
  const server = tool.value.mcp_servers[idx]
  if (server) delete mcpTestResults.value[server.uid]
  tool.value.mcp_servers.splice(idx, 1)
}

async function testMcpServer(server: McpServer) {
  mcpTestResults.value = { ...mcpTestResults.value, [server.uid]: { loading: true } }
  try {
    const config: any = {
      transport: server.transport,
      command: server.command,
      args: server.args,
      url: server.url,
      headers: server.headers || [],
      tool_id: tool.value.id,
    }
    const res = await testMcpConnection(config)
    if (res.success) {
      const tools = (res.tools || []).map((t: any) => ({ name: t.name, description: t.description || t.name }))
      server.discovered_tools = tools
      mcpTestResults.value = { ...mcpTestResults.value, [server.uid]: { loading: false, result: `${tools.length} tool(s) found` } }
      selectedMcpServer.value = server
    } else {
      mcpTestResults.value = { ...mcpTestResults.value, [server.uid]: { loading: false, result: `Error: ${res.error}` } }
    }
  } catch (e: any) {
    mcpTestResults.value = { ...mcpTestResults.value, [server.uid]: { loading: false, result: `Error: ${e.message}` } }
  }
}

// MCP tool selection
const selectedMcpServer = ref<McpServer | null>(null)

function toggleMcpTool(server: McpServer, toolName: string) {
  if (!server.allowed_tools) server.allowed_tools = []
  const idx = server.allowed_tools.indexOf(toolName)
  if (idx > -1) {
    server.allowed_tools.splice(idx, 1)
  } else {
    server.allowed_tools.push(toolName)
  }
}

function selectAllMcpTools(server: McpServer) {
  server.allowed_tools = (server.discovered_tools || []).map(t => t.name)
}

function clearAllMcpTools(server: McpServer) {
  server.allowed_tools = []
}


function addFunction() {
  const uid = getUid(6)
  const fn: AgentFunction = {
    uid,
    name: `func_${uid}`,
    description: '',
    is_enabled: true,
    is_deleted: false,
    function_string: `def func_${uid}(input: str) -> str:\n    """Description of what this function does."""\n    return input`,
  }
  tool.value.agent_functions.push(fn)
  selectedFunction.value = fn
}

function removeFunction(fn: AgentFunction) {
  const idx = tool.value.agent_functions.indexOf(fn)
  if (idx > -1) {
    tool.value.agent_functions.splice(idx, 1)
    if (selectedFunction.value === fn) selectedFunction.value = null
  }
}

function exportTool() {
  showExportModal.value = true
}

async function onExportConfirm(exportName: string, exportDescription: string, version: number) {
  if (!tool.value.export_uid) tool.value.export_uid = getUid()
  tool.value.export_version = version
  await saveTool(tool.value)

  const data: any = deepClone(tool.value)
  delete data.id
  delete data.created_at
  delete data.updated_at
  // Convert image URL to base64 for portability
  if (data.image_url) {
    const b64 = await imageUrlToBase64(data.image_url)
    data.image_url = b64 || ''
  }
  data._export_type = 'tool'
  data._export_name = exportName
  data._export_description = exportDescription
  data._export_date = new Date().toISOString()
  data._pip_packages = tool.value.pip_dependencies || []
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${exportName || 'tool'}.json`
  a.click()
  URL.revokeObjectURL(url)
}

async function selectFunction(fn: AgentFunction) {
  if (selectedFunction.value === fn) {
    selectedFunction.value = null
    return
  }
  selectedFunction.value = null
  await nextTick()
  selectedFunction.value = fn
}


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

  const { promise, abort } = wsAiAssistTool(
    aiAssistDescription.value,
    aiAssistModel.value,
    tool.value,
    (event: AiAssistEvent) => {
      if (event.type === 'status') {
        aiAssistStatus.value = event.text || ''
      } else if (event.type === 'delta') {
        aiAssistStreamJson.value += event.text || ''
      } else if (event.type === 'result') {
        aiAssistResult.value = event.tool_config || null
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
  if (aiAssistResult.value) {
    mergeAiResult(aiAssistResult.value)
    toast('AI configuration applied', 'success')
    showAiAssist.value = false
  }
}

function mergeAiResult(config: Record<string, any>) {
  // Simple fields
  const simpleFields = ['name', 'type', 'tag', 'description', 'prompt', 'system_prompt', 'model',
    'endpoint_url', 'endpoint_method', 'endpoint_headers', 'endpoint_body', 'endpoint_query',
    'endpoint_timeout', 'response_structure'] as const
  for (const key of simpleFields) {
    if (config[key] !== undefined) {
      ;(tool.value as any)[key] = config[key]
    }
  }

  // pip_dependencies
  if (Array.isArray(config.pip_dependencies)) {
    tool.value.pip_dependencies = config.pip_dependencies
  }

  // env_variables — merge by name to preserve existing values
  if (Array.isArray(config.env_variables) && config.env_variables.length) {
    const existingByName = new Map(
      tool.value.env_variables.map((v: any) => [v.name, v])
    )
    tool.value.env_variables = config.env_variables.map((v: any) => ({
      name: v.name || '',
      description: v.description || existingByName.get(v.name)?.description || '',
      type: v.type ?? existingByName.get(v.name)?.type ?? PropertyType.TEXT,
    }))
  }

  // request_inputs — full replacement with proper Property shape
  if (Array.isArray(config.request_inputs) && config.request_inputs.length) {
    tool.value.request_inputs = config.request_inputs.map((inp: any, idx: number) => ({
      name: inp.name || '',
      value: '',
      description: inp.description || '',
      type: inp.type ?? PropertyType.TEXT,
      is_required: inp.is_required ?? true,
      locked: true,
      index: idx,
      is_default: inp.is_default ?? (idx === 0),
      data: inp.data ?? null,
    }))
  }

  // agent_functions — full replacement with defaults
  if (Array.isArray(config.agent_functions) && config.agent_functions.length) {
    tool.value.agent_functions = config.agent_functions.map((fn: any) => ({
      uid: getUid(6),
      name: fn.name || '',
      description: fn.description || '',
      is_enabled: true,
      is_deleted: false,
      function_string: fn.function_string || '',
    }))
    // Auto-select first function
    selectedFunction.value = tool.value.agent_functions[0] || null
  }

  // Resync KV editors for endpoint fields
  loadKvFields()
}
</script>

<template>
  <div class="flex h-full">
    <!-- Left: Settings + Inputs -->
    <div class="w-72 bg-gray-900 border-r border-gray-800 flex flex-col">
      <!-- Header -->
      <div class="p-4 border-b border-gray-800">
        <div class="flex items-center gap-3">
          <button @click="router.push('/tools')" class="text-gray-400 hover:text-gray-50 text-sm">&larr;</button>
          <h1 class="text-lg font-bold truncate">{{ route.query.new ? 'New Tool' : tool.name || 'Edit Tool' }}</h1>
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
            <input v-model="tool.name" class="input-sm" />
          </div>

          <div>
            <label class="block text-xs text-gray-400 mb-1">Type</label>
            <select v-model.number="tool.type" class="input-sm">
              <option :value="ToolType.LLM">LLM</option>
              <option :value="ToolType.Endpoint">Endpoint</option>
              <option :value="ToolType.Agent">Agent</option>
            </select>
          </div>

          <div>
            <label class="block text-xs text-gray-400 mb-1">Description</label>
            <input v-model="tool.description" class="input-sm" />
          </div>

          <div>
            <label class="block text-xs text-gray-400 mb-1">Tag</label>
            <input v-model="tool.tag" class="input-sm" />
          </div>

          <div class="flex items-center gap-2">
            <label class="text-xs text-gray-400">Enabled</label>
            <input type="checkbox" v-model="tool.is_enabled" />
          </div>

          <!-- Tool Image -->
          <div>
            <label class="block text-xs text-gray-400 mb-1">Image</label>
            <div class="flex items-center gap-3">
              <div v-if="tool.image_url" class="relative group">
                <img :src="tool.image_url" class="w-16 h-16 rounded-lg object-cover border border-gray-700 bg-black" />
                <button @click="removeImage" class="absolute -top-1.5 -right-1.5 w-5 h-5 bg-red-600 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity" title="Remove image">x</button>
              </div>
              <LetterAvatar v-else :letter="tool.name" :size="64" />
              <button @click="imageFileInput?.click()" :disabled="uploadingImage" class="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs text-gray-300 transition-colors disabled:opacity-50">
                {{ uploadingImage ? 'Uploading...' : 'Upload' }}
              </button>
              <input ref="imageFileInput" type="file" accept="image/*" class="hidden" @change="onImageSelected" />
            </div>
          </div>

          <!-- LLM-specific settings -->
          <template v-if="isLLM">
            <div>
              <label class="block text-xs text-gray-400 mb-1">Model</label>
              <ModelSelectDropdown v-model="tool.model" :models="models" />
            </div>
          </template>

          <!-- Agent-specific settings -->
          <template v-if="isAgent">
            <div>
              <label class="block text-xs text-gray-400 mb-1">Model</label>
              <ModelSelectDropdown v-model="tool.model" :models="models" />
            </div>

            <!-- Pip Dependencies -->
            <div>
              <label class="block text-xs text-gray-400 mb-1">Pip Dependencies</label>
              <div class="flex gap-1 mb-1">
                <input v-model="pipInput" @keydown.enter.prevent="addPipDep" placeholder="package name" class="flex-1 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" />
                <button @click="addPipDep" class="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs">+</button>
              </div>
              <div class="flex flex-wrap gap-1">
                <span v-for="(pkg, idx) in tool.pip_dependencies" :key="idx" class="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-800 border border-gray-700 rounded text-xs">
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
            <div>
              <div class="flex items-center justify-between mb-1">
                <label class="block text-xs text-gray-400">Env Variables</label>
                <button @click="addEnvVar" class="text-xs text-blue-400 hover:text-blue-300">+ Add</button>
              </div>
              <div class="space-y-1">
                <div v-for="(v, idx) in tool.env_variables" :key="idx" class="p-1.5 bg-gray-800/50 rounded border border-gray-800 space-y-1">
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
              <div v-if="tool.env_variables.length && tool.id" class="mt-2">
                <button v-if="!showEnvValues" @click="loadEnvVarValues" class="text-xs text-blue-400 hover:text-blue-300 transition-colors">Set Values</button>
                <div v-else class="p-2 bg-gray-800/70 rounded border border-gray-700 space-y-1.5">
                  <div class="flex items-center justify-between">
                    <span class="text-xs text-gray-400 font-medium">Variable Values</span>
                    <button @click="showEnvValues = false" class="text-xs text-gray-500 hover:text-gray-300">&times;</button>
                  </div>
                  <div v-for="v in tool.env_variables" :key="v.name" class="space-y-0.5">
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
              <p v-if="tool.env_variables.length && !tool.id" class="text-xs text-gray-600 mt-1">Save the tool first to set variable values.</p>
              <p v-if="tool.env_variables.length" class="text-xs text-gray-600 mt-1">In code, use get_var("VAR_NAME") or access as a module global.</p>
            </div>

            <!-- MCP Servers -->
            <div>
              <div class="flex items-center justify-between mb-1">
                <label class="block text-xs text-gray-400">MCP Servers</label>
                <button @click="addMcpServer" class="text-xs text-blue-400 hover:text-blue-300">+ Add</button>
              </div>
              <div class="space-y-2">
                <div v-for="(srv, idx) in tool.mcp_servers" :key="srv.uid" class="p-1.5 bg-gray-800/50 rounded border border-gray-800 space-y-1">
                  <div class="flex items-center gap-1">
                    <input v-model="srv.name" placeholder="Name" class="flex-1 px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" />
                    <input type="checkbox" v-model="srv.is_enabled" title="Enabled" />
                    <button @click="removeMcpServer(idx)" class="text-red-400 hover:text-red-300 text-xs">&times;</button>
                  </div>
                  <select v-model.number="srv.transport" class="w-full px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500">
                    <option :value="0">Stdio</option>
                    <option :value="1">HTTP / SSE</option>
                  </select>
                  <template v-if="srv.transport === 0">
                    <input v-model="srv.command" placeholder="Command (e.g. npx)" class="w-full px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500" />
                    <input :value="srv.args.join(', ')" @change="srv.args = ($event.target as HTMLInputElement).value.split(',').map(s => s.trim()).filter(Boolean)" placeholder="Args (comma-separated)" class="w-full px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500" />
                  </template>
                  <template v-else>
                    <input v-model="srv.url" placeholder="http://localhost:3001/sse" class="w-full px-1.5 py-0.5 bg-gray-800 border border-gray-700 rounded text-xs font-mono focus:outline-none focus:border-blue-500" />
                    <KeyValueEditor v-model="srv.headers" :variables="tool.env_variables.map(v => v.name).filter(Boolean)" label="Headers" keyPlaceholder="Authorization" valuePlaceholder="Bearer {{API_TOKEN}}" />
                  </template>
                  <div class="flex items-center gap-1">
                    <button @click="testMcpServer(srv)" :disabled="mcpTestResults[srv.uid]?.loading" class="px-2 py-0.5 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 rounded text-xs transition-colors">
                      {{ mcpTestResults[srv.uid]?.loading ? 'Testing...' : 'Test' }}
                    </button>
                    <span v-if="mcpTestResults[srv.uid]?.result" class="text-xs" :class="mcpTestResults[srv.uid]?.result?.startsWith('Error') ? 'text-red-400' : 'text-green-400'">
                      {{ mcpTestResults[srv.uid]?.result }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- Endpoint-specific settings -->
          <template v-if="isEndpoint">
            <div>
              <label class="block text-xs text-gray-400 mb-1">Method</label>
              <select v-model.number="tool.endpoint_method" class="input-sm">
                <option :value="0">GET</option>
                <option :value="1">POST</option>
                <option :value="2">PUT</option>
                <option :value="3">DELETE</option>
              </select>
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">Timeout (seconds)</label>
              <input v-model.number="tool.endpoint_timeout" type="number" min="1" class="input-sm" />
            </div>
          </template>
        </div>

        <!-- Inputs -->
        <div class="p-4">
          <div class="flex items-center justify-between mb-2">
            <div class="text-xs text-gray-500 uppercase font-medium">Inputs</div>
            <button @click="addInput" class="text-xs text-blue-400 hover:text-blue-300">+ Add</button>
          </div>
          <div class="space-y-2">
            <div v-for="(inp, idx) in tool.request_inputs" :key="idx" class="space-y-1 p-2 bg-gray-800/50 rounded border border-gray-800">
              <div class="flex items-center gap-1">
                <input v-model="inp.name" placeholder="Name" class="flex-1 px-1.5 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500" />
                <button @click="configInput = inp; showInputConfig = true" type="button" title="Configure input" class="shrink-0 p-1 text-gray-500 hover:text-gray-300 transition-colors">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z" /><circle cx="12" cy="12" r="3" /></svg>
                </button>
                <button v-if="!inp.locked" @click="removeInput(idx)" class="text-red-400 hover:text-red-300 text-xs">x</button>
              </div>
              <DynamicInput v-model="inp.value" :type="inp.type" :data="inp.data" placeholder="Test value..." :label="inp.name" />
            </div>
          </div>
        </div>

        <!-- Recent Runs -->
        <div class="p-4 border-t border-gray-800">
          <button @click="showRunHistory = !showRunHistory" class="flex items-center justify-between w-full text-xs text-gray-500 uppercase font-medium mb-2">
            <span>Recent Runs ({{ toolRuns.length }})</span>
            <span class="text-gray-600">{{ showRunHistory ? '&#9650;' : '&#9660;' }}</span>
          </button>
          <div v-if="showRunHistory" class="space-y-1 max-h-48 overflow-auto">
            <div v-if="toolRuns.length === 0" class="text-xs text-gray-600">No runs yet</div>
            <div
              v-for="r in toolRuns"
              :key="r.id"
              class="flex items-center gap-2 px-2 py-1.5 rounded text-xs cursor-pointer hover:bg-gray-800 transition-colors group"
              @click="router.push(`/pipeline-run/${r.id}`)"
            >
              <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="{
                'bg-gray-400': r.status === PipelineStatusType.Pending,
                'bg-blue-400': r.status === PipelineStatusType.Running,
                'bg-green-400': r.status === PipelineStatusType.Completed,
                'bg-red-400': r.status === PipelineStatusType.Failed,
                'bg-yellow-400': r.status === PipelineStatusType.Paused,
              }"></span>
              <span class="truncate flex-1" :class="statusColors[r.status]">{{ statusLabels[r.status] }}</span>
              <span class="text-gray-600 shrink-0">{{ r.created_at ? new Date(r.created_at).toLocaleDateString() : '' }}</span>
              <button @click.stop="deleteRun(r.id)" class="text-red-400/0 group-hover:text-red-400 hover:!text-red-300 shrink-0">&times;</button>
            </div>
          </div>
        </div>
      </template>
      </div><!-- /scrollable -->

      <!-- Actions -->
      <div class="p-3 border-t border-gray-800 space-y-2">
        <button v-if="auth.canEdit('tools')" @click="save" :disabled="saving" class="w-full px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors">
          {{ saving ? 'Saving...' : 'Save' }}
        </button>
        <button @click="test" :disabled="testing" class="w-full px-3 py-2 bg-green-600 hover:bg-green-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors">
          {{ testing ? 'Testing...' : 'Test' }}
        </button>
        <div class="flex gap-2">
          <button @click="exportTool" class="flex-1 px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition-colors">
            Export
          </button>
          <button v-if="auth.canDelete('tools')" @click="deleteTool" class="flex-1 px-3 py-2 bg-red-900/40 hover:bg-red-900/60 text-red-400 rounded-lg text-sm font-medium transition-colors">
            Delete
          </button>
        </div>
      </div>
    </div>

    <!-- Middle: Type-specific content -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <!-- LLM: Prompt -->
      <template v-if="isLLM && !loading">
        <div class="flex-1 flex flex-col p-6 overflow-auto">
          <div class="flex items-center gap-3 mb-4">
            <h2 class="text-lg font-bold text-purple-400">LLM</h2>
          </div>
          <div class="space-y-4 max-w-4xl">
            <div>
              <label class="block text-sm text-gray-400 mb-1">Prompt <span class="text-gray-600 text-xs" v-pre>(use {{ variableName }} for interpolation)</span></label>
              <TemplateInput v-model="tool.prompt" :variables="templateVariables" mode="textarea" :rows="16" inputClass="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm font-mono focus:outline-none focus:border-blue-500 resize-y" />
            </div>
            <div class="border-t border-gray-800 pt-4">
              <div class="text-sm font-medium text-gray-400 mb-2">Response Structure</div>
              <p class="text-xs text-gray-600 mb-2">Define expected output fields. The LLM will be forced to return structured JSON matching this schema.</p>
              <ResponseStructureEditor v-model="tool.response_structure" />
            </div>
          </div>
        </div>
      </template>

      <!-- Agent: System Prompt + Prompt side by side, then functions below -->
      <template v-if="isAgent && !loading">
        <div class="flex flex-col flex-1 overflow-hidden">
          <!-- Prompts -->
          <div class="p-6 border-b border-gray-800">
            <h2 class="text-lg font-bold text-orange-400 mb-4">Agent</h2>
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="block text-sm text-gray-400 mb-1">System Prompt</label>
                <TemplateInput v-model="tool.system_prompt" :variables="templateVariables" mode="textarea" :rows="6" inputClass="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm font-mono focus:outline-none focus:border-blue-500 resize-y" />
              </div>
              <div>
                <label class="block text-sm text-gray-400 mb-1">Prompt <span class="text-gray-600 text-xs" v-pre>(use {{ variableName }})</span></label>
                <TemplateInput v-model="tool.prompt" :variables="templateVariables" mode="textarea" :rows="6" inputClass="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm font-mono focus:outline-none focus:border-blue-500 resize-y" />
              </div>
            </div>
          </div>

          <!-- MCP Tool Selection -->
          <div v-if="tool.mcp_servers.length" class="px-6 py-4 border-b border-gray-800">
            <div class="flex items-center gap-3 mb-3">
              <h3 class="text-sm font-bold text-gray-300 uppercase">MCP Tool Selection</h3>
              <div class="flex gap-1">
                <button
                  v-for="srv in tool.mcp_servers"
                  :key="srv.uid"
                  @click="selectedMcpServer = selectedMcpServer === srv ? null : srv"
                  class="px-2 py-0.5 rounded text-xs transition-colors"
                  :class="selectedMcpServer === srv ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'"
                >
                  {{ srv.name }}
                  <span v-if="srv.allowed_tools?.length" class="ml-1 text-blue-300">({{ srv.allowed_tools?.length }})</span>
                </button>
              </div>
            </div>
            <div v-if="selectedMcpServer" class="bg-gray-800/50 rounded-lg border border-gray-700 p-3">
              <template v-if="selectedMcpServer.discovered_tools?.length">
                <div class="flex items-center justify-between mb-2">
                  <span class="text-xs text-gray-400">
                    {{ !selectedMcpServer.allowed_tools?.length ? 'All' : selectedMcpServer.allowed_tools.length + ' of ' + selectedMcpServer.discovered_tools.length }} tool(s) enabled
                    <span v-if="!selectedMcpServer.allowed_tools?.length" class="text-gray-500">(no filter)</span>
                  </span>
                  <div class="flex gap-2">
                    <button @click="selectAllMcpTools(selectedMcpServer!)" class="text-xs text-blue-400 hover:text-blue-300">Select All</button>
                    <button @click="clearAllMcpTools(selectedMcpServer!)" class="text-xs text-gray-500 hover:text-gray-300">Clear (allow all)</button>
                  </div>
                </div>
                <div class="grid grid-cols-2 lg:grid-cols-3 gap-1 max-h-48 overflow-auto">
                  <label
                    v-for="t in selectedMcpServer.discovered_tools"
                    :key="t.name"
                    class="flex items-start gap-2 px-2 py-1.5 rounded cursor-pointer text-xs transition-colors hover:bg-gray-700/50"
                    :class="!selectedMcpServer!.allowed_tools?.length || selectedMcpServer!.allowed_tools.includes(t.name) ? 'text-gray-200' : 'text-gray-500'"
                    :title="t.description"
                  >
                    <input
                      type="checkbox"
                      :checked="selectedMcpServer!.allowed_tools?.includes(t.name)"
                      @change="toggleMcpTool(selectedMcpServer!, t.name)"
                      class="mt-0.5 shrink-0"
                    />
                    <span class="truncate">{{ t.name }}</span>
                  </label>
                </div>
              </template>
              <div v-else class="text-xs text-gray-500 py-2">
                Click "Test" on this server in the sidebar to load available tools.
              </div>
            </div>
          </div>

          <!-- Response Structure -->
          <div class="px-6 py-4 border-b border-gray-800">
            <div class="text-sm font-medium text-gray-400 mb-2">Response Structure</div>
            <p class="text-xs text-gray-600 mb-2">Define expected output fields. After the agent loop, the output will be formatted into structured JSON.</p>
            <ResponseStructureEditor v-model="tool.response_structure" />
          </div>

          <!-- Agent Functions -->
          <div class="flex flex-1 overflow-hidden">
            <!-- Function list -->
            <div class="w-56 border-r border-gray-800 flex flex-col">
              <div class="p-3 border-b border-gray-800 flex items-center justify-between">
                <div class="text-xs text-gray-500 uppercase font-medium">Functions</div>
                <button @click="addFunction" class="text-xs text-blue-400 hover:text-blue-300">+ Add</button>
              </div>
              <div class="flex-1 overflow-auto p-2 space-y-1">
                <div
                  v-for="fn in tool.agent_functions.filter(f => !f.is_deleted)"
                  :key="fn.uid"
                  @click="selectFunction(fn)"
                  class="px-2 py-1.5 rounded text-sm cursor-pointer transition-colors flex items-center gap-2"
                  :class="selectedFunction === fn ? 'bg-orange-500/20 text-orange-300 border border-orange-500/30' : 'text-gray-300 hover:bg-gray-800'"
                >
                  <span class="w-1.5 h-1.5 rounded-full" :class="fn.is_enabled ? 'bg-green-400' : 'bg-gray-600'"></span>
                  <span class="truncate">{{ fn.name }}</span>
                </div>
                <div v-if="tool.agent_functions.filter(f => !f.is_deleted).length === 0" class="text-xs text-gray-600 p-2">
                  No functions yet
                </div>
              </div>
            </div>

            <!-- Function editor -->
            <div class="flex-1 flex flex-col overflow-hidden">
              <template v-if="selectedFunction">
                <div class="p-3 border-b border-gray-800 flex items-center gap-3">
                  <input v-model="selectedFunction.name" placeholder="Function name" class="flex-1 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-sm focus:outline-none focus:border-blue-500" />
                  <label class="flex items-center gap-1 text-xs text-gray-400">
                    <input type="checkbox" v-model="selectedFunction.is_enabled" /> Enabled
                  </label>
                  <button @click="removeFunction(selectedFunction)" class="text-red-400 hover:text-red-300 text-sm">Delete</button>
                </div>
                <div class="p-3 border-b border-gray-800">
                  <input v-model="selectedFunction.description" placeholder="Description of what this function does" class="w-full px-2 py-1 bg-gray-800 border border-gray-700 rounded text-sm focus:outline-none focus:border-blue-500" />
                </div>
                <div class="flex-1 p-3 overflow-hidden">
                  <CodeEditor v-model="selectedFunction.function_string" language="python" height="100%" :fileUri="`file:///workspace/tool_${tool.id}_${selectedFunction.uid}.py`" />
                </div>
              </template>
              <div v-else class="flex-1 flex items-center justify-center text-gray-600 text-sm">
                Select or create a function
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Endpoint: URL + Query Params + Headers + Body -->
      <template v-if="isEndpoint && !loading">
        <div class="flex-1 p-6 overflow-auto">
          <h2 class="text-lg font-bold text-green-400 mb-4">Endpoint</h2>
          <div class="space-y-5 max-w-4xl">
            <div>
              <label class="block text-sm text-gray-400 mb-1">URL <span class="text-gray-600 text-xs" v-pre>(use {{ variableName }} for interpolation)</span></label>
              <TemplateInput v-model="tool.endpoint_url" :variables="templateVariables" mode="input" placeholder="https://api.example.com/..." inputClass="input-base" />
            </div>
            <KeyValueEditor v-model="endpointQuery" :variables="templateVariables" label="Query Params" keyPlaceholder="param" valuePlaceholder="value" />
            <KeyValueEditor v-model="endpointHeaders" :variables="templateVariables" label="Headers" keyPlaceholder="Header-Name" valuePlaceholder="Header value" />
            <KeyValueEditor v-if="endpointHasBody" v-model="endpointBody" :variables="templateVariables" label="Body" keyPlaceholder="key" valuePlaceholder="value" />
            <div class="border-t border-gray-800 pt-4">
              <div class="text-sm font-medium text-gray-400 mb-2">Response Structure</div>
              <p class="text-xs text-gray-600 mb-2">Define expected output fields to enable dot-notation access in pipelines.</p>
              <ResponseStructureEditor v-model="tool.response_structure" />
            </div>
          </div>
        </div>
      </template>
    </div>

    <InputConfigModal v-model="showInputConfig" :input="configInput" />

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
              <label class="block text-xs text-gray-400 mb-1">Describe what you want this tool to do</label>
              <textarea
                v-model="aiAssistDescription"
                rows="3"
                placeholder="e.g. Create an LLM tool that translates text to any language with a Language input..."
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
              Apply to Tool
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
      :defaultName="tool.name"
      :defaultDescription="tool.description"
      :defaultVersion="tool.export_version || 1"
      @confirm="onExportConfirm"
    />

  </div>
</template>
