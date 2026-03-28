<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { getSettings, saveSettings, getCustomSettings, saveCustomSettings, getModels, createModel, updateModel, deleteModel, reorderModels } from '@/services/settingsService'
import type { Settings, CustomSettingsGroup, Model } from '@/models'
import { PropertyType } from '@/models'
import { useToast } from '@/composables/useToast'
import { useTheme } from '@/composables/useTheme'
import { invalidateModels } from '@/composables/useModels'
import ModelEditForm from '@/components/shared/ModelEditForm.vue'
const { show: toast } = useToast()
const { theme, toggle: toggleTheme } = useTheme()

const activeTab = ref<'system' | 'custom' | 'models'>('system')

// System settings
const settings = ref<Partial<Settings>>({})
const loading = ref(true)
const saved = ref(false)

// Custom settings
const customGroups = ref<CustomSettingsGroup[]>([])
const customLoading = ref(false)
const customSaved = ref(false)

// Models
const allModels = ref<Model[]>([])
const modelsLoading = ref(false)
const editingModel = ref<Partial<Model> | null>(null)
const isNewModel = ref(false)

const anthropicModels = computed(() => allModels.value.filter(m => m.provider === 'anthropic'))
const openaiModels = computed(() => allModels.value.filter(m => m.provider === 'openai'))
const geminiModels = computed(() => allModels.value.filter(m => m.provider === 'google'))
const xaiModels = computed(() => allModels.value.filter(m => m.provider === 'xai'))
const localModels = computed(() => allModels.value.filter(m => m.provider === 'local'))
const hasAnthropicKey = computed(() => !!settings.value.ANTHROPIC_API_KEY)
const hasOpenaiKey = computed(() => !!settings.value.OPENAI_API_KEY)
const hasGoogleKey = computed(() => !!settings.value.GOOGLE_API_KEY)
const hasXaiKey = computed(() => !!settings.value.XAI_API_KEY)
const hasLocalUrl = computed(() => !!settings.value.LOCAL_LLM_URL)

onMounted(async () => {
  const data = await getSettings()
  settings.value = data
  loading.value = false
})

watch(activeTab, async (tab) => {
  if (tab === 'custom' && customGroups.value.length === 0) {
    customLoading.value = true
    customGroups.value = await getCustomSettings()
    customLoading.value = false
  }
  if (tab === 'models') {
    await loadAllModels()
  }
})

async function loadAllModels() {
  modelsLoading.value = true
  allModels.value = await getModels()
  modelsLoading.value = false
}

function startAddModel(provider: 'anthropic' | 'openai' | 'google' | 'xai' | 'local') {
  isNewModel.value = true
  editingModel.value = { model_id: provider === 'local' ? 'local-' : '', name: '', provider, input_cost: 0, output_cost: 0 }
}

function startEditModel(model: Model) {
  isNewModel.value = false
  editingModel.value = { ...model }
}

function cancelEdit() {
  editingModel.value = null
}

async function saveModelEdit() {
  if (!editingModel.value) return
  if (isNewModel.value) {
    await createModel(editingModel.value)
  } else {
    await updateModel(editingModel.value.id!, editingModel.value)
  }
  editingModel.value = null
  invalidateModels()
  await loadAllModels()
  toast('Model saved', 'success')
}

async function removeModel(model: Model) {
  if (!confirm(`Delete "${model.name}"?`)) return
  await deleteModel(model.id)
  invalidateModels()
  await loadAllModels()
  toast('Model deleted', 'success')
}

// Drag & drop reordering
const dragIndex = ref<number | null>(null)
const dragProvider = ref<string | null>(null)

function onDragStart(index: number, provider: string) {
  dragIndex.value = index
  dragProvider.value = provider
}

function onDragOver(e: DragEvent, index: number, provider: string) {
  if (dragProvider.value !== provider) return
  e.preventDefault()
  const target = (e.currentTarget as HTMLElement)
  const rect = target.getBoundingClientRect()
  const mid = rect.top + rect.height / 2
  if (e.clientY < mid) {
    target.classList.remove('border-b-blue-500')
    target.classList.add('border-t-blue-500', 'border-t-2')
  } else {
    target.classList.remove('border-t-blue-500', 'border-t-2')
    target.classList.add('border-b-blue-500', 'border-b-2')
  }
}

function onDragLeave(e: DragEvent) {
  const el = e.currentTarget as HTMLElement
  el.classList.remove('border-t-blue-500', 'border-t-2', 'border-b-blue-500', 'border-b-2')
}

async function onDrop(e: DragEvent, dropIndex: number, provider: string) {
  const el = e.currentTarget as HTMLElement
  el.classList.remove('border-t-blue-500', 'border-t-2', 'border-b-blue-500', 'border-b-2')
  if (dragProvider.value !== provider || dragIndex.value === null) return

  const list = provider === 'anthropic' ? anthropicModels.value : provider === 'openai' ? openaiModels.value : provider === 'google' ? geminiModels.value : provider === 'xai' ? xaiModels.value : localModels.value
  const fromIdx = dragIndex.value
  if (fromIdx === dropIndex) return

  // Determine if dropping above or below
  const rect = el.getBoundingClientRect()
  const mid = rect.top + rect.height / 2
  let toIdx = e.clientY < mid ? dropIndex : dropIndex + 1
  if (fromIdx < toIdx) toIdx--

  const items = [...list]
  const [moved] = items.splice(fromIdx, 1)
  items.splice(toIdx, 0, moved)

  await reorderModels(items.map(m => m.id))
  invalidateModels()
  await loadAllModels()
  toast('Model order updated', 'success')

  dragIndex.value = null
  dragProvider.value = null
}

function onDragEnd() {
  dragIndex.value = null
  dragProvider.value = null
}

async function saveDefaultModel() {
  await saveSettings({ DEFAULT_MODEL: settings.value.DEFAULT_MODEL })
  toast('Default model updated', 'success')
}

async function save() {
  await saveSettings(settings.value)
  saved.value = true
  toast('Settings saved', 'success')
  setTimeout(() => { saved.value = false }, 2000)
}

async function saveCustom() {
  const items: { resource_type: string; resource_id: string; name: string; value: string }[] = []
  for (const group of customGroups.value) {
    for (const v of group.variables) {
      items.push({ resource_type: group.resource_type, resource_id: group.resource_id, name: v.name, value: v.value })
    }
  }
  await saveCustomSettings(items)
  customSaved.value = true
  setTimeout(() => { customSaved.value = false }, 2000)
  toast('Custom settings saved', 'success')
}
</script>

<template>
  <div class="flex flex-col h-full p-6">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold">Settings</h1>
    </div>

    <!-- Tab bar -->
    <div class="flex gap-1 mb-6">
      <button
        @click="activeTab = 'system'"
        class="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
        :class="activeTab === 'system' ? 'bg-gray-800 text-gray-100' : 'text-gray-400 hover:text-gray-300 hover:bg-gray-800/50'"
      >
        System
      </button>
       <button
        @click="activeTab = 'models'"
        class="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
        :class="activeTab === 'models' ? 'bg-gray-800 text-gray-100' : 'text-gray-400 hover:text-gray-300 hover:bg-gray-800/50'"
      >
        Models
      </button>
      <button
        @click="activeTab = 'custom'"
        class="px-4 py-2 text-sm font-medium rounded-lg transition-colors"
        :class="activeTab === 'custom' ? 'bg-gray-800 text-gray-100' : 'text-gray-400 hover:text-gray-300 hover:bg-gray-800/50'"
      >
        Custom Variables
      </button>
     
    </div>

    <!-- Scrollable content area -->
    <div class="flex-1 overflow-y-auto min-h-0 pb-20">

      <!-- ═══════════════ System Settings Tab ═══════════════ -->
      <div v-if="activeTab === 'system'">
        <div v-if="loading" class="text-gray-400">Loading...</div>
        <div v-else class="max-w-3xl space-y-6">

          <!-- Appearance -->
          <section class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">Appearance</h2>
            </div>
            <div class="p-5">
              <div class="flex items-center justify-between">
                <div>
                  <div class="text-sm font-medium text-gray-300">Theme</div>
                  <div class="text-xs text-gray-500 mt-0.5">Switch between dark and light mode</div>
                </div>
                <button
                  @click="toggleTheme"
                  class="flex items-center gap-2 px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm font-medium hover:bg-gray-700 transition-colors"
                >
                  <svg v-if="theme === 'dark'" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
                  </svg>
                  <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
                  </svg>
                  {{ theme === 'dark' ? 'Dark' : 'Light' }}
                </button>
              </div>
            </div>
          </section>

          <!-- Integrations -->
          <section class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">Integrations</h2>
            </div>
            <div class="p-5 space-y-4">
              <div class="text-sm font-medium text-gray-300">GitHub</div>
              <div>
                <label class="block text-xs text-gray-500 mb-1">Personal Access Token</label>
                <input
                  v-model="settings.GITHUB_TOKEN"
                  type="password"
                  class="input-base"
                />
              </div>
            </div>
          </section>

          <!-- Database -->
          <section class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">Database</h2>
              <p class="text-xs text-gray-500 mt-1">Changes require an app restart to take effect.</p>
            </div>
            <div class="p-5 space-y-4">
              <div>
                <label class="block text-xs text-gray-500 mb-1">Database Type</label>
                <select
                  v-model="settings.DB_TYPE"
                  class="input-base"
                >
                  <option value="sqlite">SQLite</option>
                  <option value="mssql">MS SQL Server</option>
                  <option value="postgres">PostgreSQL</option>
                  <option value="cosmos">Azure Cosmos DB</option>
                </select>
              </div>

              <div v-if="settings.DB_TYPE === 'mssql'">
                <label class="block text-xs text-gray-500 mb-1">Connection String</label>
                <input
                  v-model="settings.MSSQL_CONNECTION_STRING"
                  type="password"
                  placeholder="Driver={ODBC Driver 17 for SQL Server};Server=...;Database=...;"
                  class="input-base"
                />
              </div>

              <div v-if="settings.DB_TYPE === 'postgres'">
                <label class="block text-xs text-gray-500 mb-1">Connection String</label>
                <input
                  v-model="settings.POSTGRES_CONNECTION_STRING"
                  type="password"
                  placeholder="host=localhost dbname=sourcechat user=postgres password=..."
                  class="input-base"
                />
              </div>

              <div v-if="settings.DB_TYPE === 'cosmos'" class="space-y-4">
                <div>
                  <label class="block text-xs text-gray-500 mb-1">Endpoint URL</label>
                  <input
                    v-model="settings.COSMOS_ENDPOINT"
                    placeholder="https://myaccount.documents.azure.com:443/"
                    class="input-base"
                  />
                </div>
                <div>
                  <label class="block text-xs text-gray-500 mb-1">Account Key</label>
                  <input
                    v-model="settings.COSMOS_KEY"
                    type="password"
                    class="input-base"
                  />
                </div>
                <div>
                  <label class="block text-xs text-gray-500 mb-1">Database Name</label>
                  <input
                    v-model="settings.COSMOS_DATABASE"
                    placeholder="sourcechat"
                    class="input-base"
                  />
                </div>
              </div>
            </div>
          </section>

          <!-- Authentication -->
          <section class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">Authentication</h2>
            </div>
            <div class="p-5 space-y-5">
              <div class="flex items-center justify-between">
                <div>
                  <div class="text-sm font-medium text-gray-300">Enable Authentication</div>
                  <div class="text-xs text-gray-500 mt-0.5">Require login to access the app. Requires app restart.</div>
                </div>
                <button
                  @click="settings.AUTH_ENABLED = settings.AUTH_ENABLED === 'true' ? 'false' : 'true'"
                  class="w-10 h-6 rounded-full transition-colors relative shrink-0"
                  :class="settings.AUTH_ENABLED === 'true' ? 'bg-blue-600' : 'bg-gray-600'"
                >
                  <span class="absolute top-1 w-4 h-4 rounded-full bg-white transition-transform" :class="settings.AUTH_ENABLED === 'true' ? 'left-5' : 'left-1'" />
                </button>
              </div>

              <!-- OAuth Providers -->
              <template v-if="settings.AUTH_ENABLED === 'true'">
                <div class="border-t border-gray-800 pt-5 space-y-5">
                  <!-- Google -->
                  <div class="space-y-3">
                    <div>
                      <div class="text-sm font-medium text-gray-300">Google OAuth <span class="text-xs font-normal text-gray-500">(Optional)</span></div>
                      <div class="text-xs text-gray-500 mt-0.5">Callback: <code class="text-gray-400 bg-gray-800 px-1.5 py-0.5 rounded">&lt;your-domain&gt;/api/auth/oauth/google/callback</code></div>
                    </div>
                    <div class="grid grid-cols-2 gap-3">
                      <div>
                        <label class="block text-xs text-gray-500 mb-1">Client ID</label>
                        <input
                          v-model="settings.GOOGLE_CLIENT_ID"
                          type="text"
                          class="input-base"
                        />
                      </div>
                      <div>
                        <label class="block text-xs text-gray-500 mb-1">Client Secret</label>
                        <input
                          v-model="settings.GOOGLE_CLIENT_SECRET"
                          type="password"
                          class="input-base"
                        />
                      </div>
                    </div>
                  </div>

                  <!-- Microsoft -->
                  <div class="space-y-3">
                    <div>
                      <div class="text-sm font-medium text-gray-300">Microsoft OAuth <span class="text-xs font-normal text-gray-500">(Optional)</span></div>
                      <div class="text-xs text-gray-500 mt-0.5">Callback: <code class="text-gray-400 bg-gray-800 px-1.5 py-0.5 rounded">&lt;your-domain&gt;/api/auth/oauth/microsoft/callback</code></div>
                    </div>
                    <div class="grid grid-cols-2 gap-3">
                      <div>
                        <label class="block text-xs text-gray-500 mb-1">Client ID</label>
                        <input
                          v-model="settings.MICROSOFT_CLIENT_ID"
                          type="text"
                          class="input-base"
                        />
                      </div>
                      <div>
                        <label class="block text-xs text-gray-500 mb-1">Client Secret</label>
                        <input
                          v-model="settings.MICROSOFT_CLIENT_SECRET"
                          type="password"
                          class="input-base"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </template>
            </div>
          </section>

          <!-- Tool Execution -->
          <section class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">Tool Execution</h2>
            </div>
            <div class="p-5">
              <div class="flex items-center justify-between">
                <div>
                  <div class="text-sm font-medium text-gray-300">Safe Mode</div>
                  <div class="text-xs text-gray-500 mt-0.5">
                    Restricts tool/trigger code to a sandboxed workspace directory. Env vars are always isolated regardless of this setting.
                  </div>
                  <div class="text-xs mt-1" :class="settings.TOOL_SAFE_MODE === 'true' ? 'text-green-400' : 'text-amber-400'">
                    {{ settings.TOOL_SAFE_MODE === 'true' ? 'Filesystem access restricted to tool workspace' : 'Unrestricted filesystem access (owner mode)' }}
                  </div>
                </div>
                <button
                  @click="settings.TOOL_SAFE_MODE = settings.TOOL_SAFE_MODE === 'true' ? 'false' : 'true'"
                  class="w-10 h-6 rounded-full transition-colors relative shrink-0 ml-4"
                  :class="settings.TOOL_SAFE_MODE === 'true' ? 'bg-green-600' : 'bg-amber-600'"
                >
                  <span class="absolute top-1 w-4 h-4 rounded-full bg-white transition-transform" :class="settings.TOOL_SAFE_MODE === 'true' ? 'left-5' : 'left-1'" />
                </button>
              </div>
            </div>
          </section>

          <!-- Azure Storage -->
          <section class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">Azure Blob Storage <span class="text-xs font-normal text-gray-500 normal-case tracking-normal">(Optional)</span></h2>
              <p class="text-xs text-gray-500 mt-1">Used for storing images uploaded to tools, triggers, and pipelines. Recommended for shared team environments where multiple users need access to uploaded assets.</p>
            </div>
            <div class="p-5 space-y-4">
              <div>
                <label class="block text-xs text-gray-500 mb-1">Connection String</label>
                <input
                  v-model="settings.AZURE_STORAGE_CONNECTION_STRING"
                  type="password"
                  placeholder="DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net"
                  class="input-base"
                />
              </div>
              <div>
                <label class="block text-xs text-gray-500 mb-1">Container Name</label>
                <input
                  v-model="settings.AZURE_STORAGE_CONTAINER"
                  type="text"
                  placeholder="tool-images"
                  class="input-base"
                />
              </div>
            </div>
          </section>

          <!-- Community -->
          <section class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div class="px-5 py-4 border-b border-gray-800">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">Community</h2>
            </div>
            <div class="p-5 space-y-3">
              <div>
                <label class="block text-sm font-medium text-gray-300 mb-1">Community Site URL</label>
                <input v-model="settings.COMMUNITY_URL" type="text" placeholder="https://your-community-site.com"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-blue-500" />
                <p class="text-xs text-gray-500 mt-1">URL of the Claire community site for importing shared tools, pipelines, and triggers.</p>
              </div>
            </div>
          </section>

          <!-- Save button -->
          <div class="flex items-center gap-3">
            <button @click="save" class="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors">
              Save Settings
            </button>
            <span v-if="saved" class="text-green-400 text-sm">Saved!</span>
          </div>
        </div>
      </div>

      <!-- ═══════════════ Custom Settings Tab ═══════════════ -->
      <div v-if="activeTab === 'custom'">
        <div v-if="customLoading" class="text-gray-400">Loading...</div>
        <div v-else-if="customGroups.length === 0" class="max-w-3xl">
          <div class="bg-gray-900 border border-gray-800 rounded-lg p-8 text-center">
            <svg class="w-10 h-10 mx-auto mb-3 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4.745 3A23.933 23.933 0 003 12c0 3.183.62 6.22 1.745 9M19.5 3c.967 2.78 1.5 5.817 1.5 9s-.533 6.22-1.5 9M8.25 8.885l1.444-.89a.75.75 0 011.105.402l2.402 7.206a.75.75 0 001.105.401l1.444-.889M13.5 2.89l2.272 1.136a.75.75 0 01.378.894l-2.4 7.202a.75.75 0 00.378.894l2.272 1.136" />
            </svg>
            <p class="text-sm text-gray-400">No custom environment variables declared by any tools or triggers.</p>
            <p class="text-xs text-gray-500 mt-1">Add env variables to Agent tools or triggers to manage them here.</p>
          </div>
        </div>
        <div v-else class="max-w-3xl space-y-6">
          <section v-for="group in customGroups" :key="group.resource_type + '-' + group.resource_id" class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800 flex items-center gap-2">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">{{ group.resource_name }}</h2>
              <span class="text-xs px-1.5 py-0.5 rounded font-medium" :class="group.resource_type === 'tool' ? 'bg-orange-500/20 text-orange-400' : 'bg-cyan-500/20 text-cyan-400'">
                {{ group.resource_type === 'tool' ? 'Tool' : 'Trigger' }}
              </span>
            </div>
            <div class="p-5 space-y-4">
              <div v-for="v in group.variables" :key="v.name">
                <div class="flex items-baseline gap-2 mb-1">
                  <label class="block text-xs text-gray-400 font-medium">{{ v.name }}</label>
                  <span v-if="v.description" class="text-xs text-gray-600">{{ v.description }}</span>
                </div>
                <input
                  v-model="v.value"
                  :type="v.type === PropertyType.PASSWORD ? 'password' : 'text'"
                  class="input-base"
                />
              </div>
            </div>
          </section>

          <!-- Save button -->
          <div class="flex items-center gap-3">
            <button @click="saveCustom" class="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors">
              Save Custom Settings
            </button>
            <span v-if="customSaved" class="text-green-400 text-sm">Saved!</span>
          </div>
        </div>
      </div>
      <!-- ═══════════════ Models Tab ═══════════════ -->
      <div v-if="activeTab === 'models'">
        <div v-if="loading" class="text-gray-400">Loading...</div>
        <div v-else class="max-w-3xl space-y-6">

          <!-- API Keys -->
          <section class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">API Keys</h2>
            </div>
            <div class="divide-y divide-gray-800">
              <div class="p-5 space-y-4">
                <div class="text-sm font-medium text-gray-300">Anthropic</div>
                <div>
                  <label class="block text-xs text-gray-500 mb-1">API Key</label>
                  <input
                    v-model="settings.ANTHROPIC_API_KEY"
                    type="password"
                    class="input-base"
                  />
                </div>
              </div>
              <div class="p-5 space-y-4">
                <div class="text-sm font-medium text-gray-300">OpenAI</div>
                <div>
                  <label class="block text-xs text-gray-500 mb-1">API Key</label>
                  <input
                    v-model="settings.OPENAI_API_KEY"
                    type="password"
                    class="input-base"
                  />
                </div>
              </div>
              <div class="p-5 space-y-4">
                <div class="text-sm font-medium text-gray-300">Google</div>
                <div>
                  <label class="block text-xs text-gray-500 mb-1">API Key</label>
                  <input
                    v-model="settings.GOOGLE_API_KEY"
                    type="password"
                    class="input-base"
                  />
                </div>
              </div>
              <div class="p-5 space-y-4">
                <div class="text-sm font-medium text-gray-300">xAI (Grok)</div>
                <div>
                  <label class="block text-xs text-gray-500 mb-1">API Key</label>
                  <input
                    v-model="settings.XAI_API_KEY"
                    type="password"
                    class="input-base"
                  />
                </div>
              </div>
              <div class="p-5 space-y-4">
                <div class="text-sm font-medium text-gray-300">Local LLM</div>
                <div>
                  <label class="block text-xs text-gray-500 mb-1">Server URL</label>
                  <input
                    v-model="settings.LOCAL_LLM_URL"
                    type="text"
                    placeholder="e.g. http://localhost:11434/v1 (Ollama) or http://localhost:1234/v1 (LM Studio)"
                    class="input-base"
                  />
                  <p class="text-xs text-gray-500 mt-1">Any OpenAI-compatible endpoint (Ollama, vLLM, LM Studio, llama.cpp)</p>
                </div>
                <div>
                  <label class="block text-xs text-gray-500 mb-1">API Key (optional)</label>
                  <input
                    v-model="settings.LOCAL_LLM_API_KEY"
                    type="password"
                    placeholder="Usually not needed — defaults to 'local'"
                    class="input-base"
                  />
                </div>
              </div>
            </div>
            <div class="px-5 py-3 border-t border-gray-800">
              <button @click="save" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors">
                Save Keys
              </button>
            </div>
          </section>

          <!-- Default Model -->
          <section v-if="hasAnthropicKey || hasOpenaiKey || hasGoogleKey || hasXaiKey || hasLocalUrl" class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">Default Model</h2>
            </div>
            <div class="p-5">
              <div class="flex items-center gap-3">
                <select
                  v-model="settings.DEFAULT_MODEL"
                  @change="saveDefaultModel"
                  class="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-blue-500"
                >
                  <option v-for="m in allModels" :key="m.id" :value="m.model_id">
                    {{ m.name }} ({{ m.model_id }})
                  </option>
                </select>
              </div>
              <p class="text-xs text-gray-500 mt-2">Used when no model is specified on a tool.</p>
            </div>
          </section>

          <!-- Anthropic Models -->
          <section v-if="hasAnthropicKey" class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">Anthropic Models</h2>
              <button @click="startAddModel('anthropic')" class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs font-medium transition-colors">
                + Add
              </button>
            </div>
            <div v-if="anthropicModels.length === 0" class="p-5 text-sm text-gray-500">No Anthropic models configured.</div>
            <div v-else>
              <template v-for="(m, idx) in anthropicModels" :key="m.id">
                <div
                  draggable="true"
                  @dragstart="onDragStart(idx, 'anthropic')"
                  @dragover="onDragOver($event, idx, 'anthropic')"
                  @dragleave="onDragLeave"
                  @drop="onDrop($event, idx, 'anthropic')"
                  @dragend="onDragEnd"
                  class="px-5 py-3 flex items-center gap-4 cursor-grab active:cursor-grabbing border-t border-b border-transparent transition-colors"
                  :class="{ 'border-b border-gray-800': idx < anthropicModels.length - 1 }"
                >
                  <svg class="w-4 h-4 text-gray-600 shrink-0" fill="currentColor" viewBox="0 0 24 24"><circle cx="9" cy="5" r="1.5"/><circle cx="15" cy="5" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="19" r="1.5"/><circle cx="15" cy="19" r="1.5"/></svg>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm font-medium text-gray-200 truncate">{{ m.name }}</div>
                    <div class="text-xs text-gray-500">{{ m.model_id }}</div>
                  </div>
                  <div class="text-xs text-gray-400 whitespace-nowrap">${{ m.input_cost }}/M in &middot; ${{ m.output_cost }}/M out</div>
                  <div class="flex gap-1">
                    <button @click="startEditModel(m)" class="p-1.5 text-gray-400 hover:text-gray-200 transition-colors" title="Edit">
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" /><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 7.125l-2.652-2.652" /></svg>
                    </button>
                    <button @click="removeModel(m)" class="p-1.5 text-gray-400 hover:text-red-400 transition-colors" title="Delete">
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" /></svg>
                    </button>
                  </div>
                </div>
                <ModelEditForm v-if="editingModel && !isNewModel && editingModel.id === m.id" :model="editingModel" :is-new="false" @save="saveModelEdit" @cancel="cancelEdit" />
              </template>
            </div>
            <ModelEditForm v-if="editingModel && isNewModel && editingModel.provider === 'anthropic'" :model="editingModel" :is-new="true" @save="saveModelEdit" @cancel="cancelEdit" />
          </section>

          <!-- OpenAI Models -->
          <section v-if="hasOpenaiKey" class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">OpenAI Models</h2>
              <button @click="startAddModel('openai')" class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs font-medium transition-colors">
                + Add
              </button>
            </div>
            <div v-if="openaiModels.length === 0" class="p-5 text-sm text-gray-500">No OpenAI models configured.</div>
            <div v-else>
              <template v-for="(m, idx) in openaiModels" :key="m.id">
                <div
                  draggable="true"
                  @dragstart="onDragStart(idx, 'openai')"
                  @dragover="onDragOver($event, idx, 'openai')"
                  @dragleave="onDragLeave"
                  @drop="onDrop($event, idx, 'openai')"
                  @dragend="onDragEnd"
                  class="px-5 py-3 flex items-center gap-4 cursor-grab active:cursor-grabbing border-t border-b border-transparent transition-colors"
                  :class="{ 'border-b border-gray-800': idx < openaiModels.length - 1 }"
                >
                  <svg class="w-4 h-4 text-gray-600 shrink-0" fill="currentColor" viewBox="0 0 24 24"><circle cx="9" cy="5" r="1.5"/><circle cx="15" cy="5" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="19" r="1.5"/><circle cx="15" cy="19" r="1.5"/></svg>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm font-medium text-gray-200 truncate">{{ m.name }}</div>
                    <div class="text-xs text-gray-500">{{ m.model_id }}</div>
                  </div>
                  <div class="text-xs text-gray-400 whitespace-nowrap">${{ m.input_cost }}/M in &middot; ${{ m.output_cost }}/M out</div>
                  <div class="flex gap-1">
                    <button @click="startEditModel(m)" class="p-1.5 text-gray-400 hover:text-gray-200 transition-colors" title="Edit">
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" /><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 7.125l-2.652-2.652" /></svg>
                    </button>
                    <button @click="removeModel(m)" class="p-1.5 text-gray-400 hover:text-red-400 transition-colors" title="Delete">
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" /></svg>
                    </button>
                  </div>
                </div>
                <ModelEditForm v-if="editingModel && !isNewModel && editingModel.id === m.id" :model="editingModel" :is-new="false" @save="saveModelEdit" @cancel="cancelEdit" />
              </template>
            </div>
            <ModelEditForm v-if="editingModel && isNewModel && editingModel.provider === 'openai'" :model="editingModel" :is-new="true" @save="saveModelEdit" @cancel="cancelEdit" />
          </section>

          <!-- Google Models -->
          <section v-if="hasGoogleKey" class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">Google Models</h2>
              <button @click="startAddModel('google')" class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs font-medium transition-colors">
                + Add
              </button>
            </div>
            <div v-if="geminiModels.length === 0" class="p-5 text-sm text-gray-500">No Google models configured.</div>
            <div v-else>
              <template v-for="(m, idx) in geminiModels" :key="m.id">
                <div
                  draggable="true"
                  @dragstart="onDragStart(idx, 'google')"
                  @dragover="onDragOver($event, idx, 'google')"
                  @dragleave="onDragLeave"
                  @drop="onDrop($event, idx, 'google')"
                  @dragend="onDragEnd"
                  class="px-5 py-3 flex items-center gap-4 cursor-grab active:cursor-grabbing border-t border-b border-transparent transition-colors"
                  :class="{ 'border-b border-gray-800': idx < geminiModels.length - 1 }"
                >
                  <svg class="w-4 h-4 text-gray-600 shrink-0" fill="currentColor" viewBox="0 0 24 24"><circle cx="9" cy="5" r="1.5"/><circle cx="15" cy="5" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="19" r="1.5"/><circle cx="15" cy="19" r="1.5"/></svg>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm font-medium text-gray-200 truncate">{{ m.name }}</div>
                    <div class="text-xs text-gray-500">{{ m.model_id }}</div>
                  </div>
                  <div class="text-xs text-gray-400 whitespace-nowrap">${{ m.input_cost }}/M in &middot; ${{ m.output_cost }}/M out</div>
                  <div class="flex gap-1">
                    <button @click="startEditModel(m)" class="p-1.5 text-gray-400 hover:text-gray-200 transition-colors" title="Edit">
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" /><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 7.125l-2.652-2.652" /></svg>
                    </button>
                    <button @click="removeModel(m)" class="p-1.5 text-gray-400 hover:text-red-400 transition-colors" title="Delete">
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" /></svg>
                    </button>
                  </div>
                </div>
                <ModelEditForm v-if="editingModel && !isNewModel && editingModel.id === m.id" :model="editingModel" :is-new="false" @save="saveModelEdit" @cancel="cancelEdit" />
              </template>
            </div>
            <ModelEditForm v-if="editingModel && isNewModel && editingModel.provider === 'google'" :model="editingModel" :is-new="true" @save="saveModelEdit" @cancel="cancelEdit" />
          </section>

          <!-- xAI (Grok) Models -->
          <section v-if="hasXaiKey" class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">xAI (Grok) Models</h2>
              <button @click="startAddModel('xai')" class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs font-medium transition-colors">
                + Add
              </button>
            </div>
            <div v-if="xaiModels.length === 0" class="p-5 text-sm text-gray-500">No xAI models configured.</div>
            <div v-else>
              <template v-for="(m, idx) in xaiModels" :key="m.id">
                <div
                  draggable="true"
                  @dragstart="onDragStart(idx, 'xai')"
                  @dragover="onDragOver($event, idx, 'xai')"
                  @dragleave="onDragLeave"
                  @drop="onDrop($event, idx, 'xai')"
                  @dragend="onDragEnd"
                  class="px-5 py-3 flex items-center gap-4 cursor-grab active:cursor-grabbing border-t border-b border-transparent transition-colors"
                  :class="{ 'border-b border-gray-800': idx < xaiModels.length - 1 }"
                >
                  <svg class="w-4 h-4 text-gray-600 shrink-0" fill="currentColor" viewBox="0 0 24 24"><circle cx="9" cy="5" r="1.5"/><circle cx="15" cy="5" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="19" r="1.5"/><circle cx="15" cy="19" r="1.5"/></svg>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm font-medium text-gray-200 truncate">{{ m.name }}</div>
                    <div class="text-xs text-gray-500">{{ m.model_id }}</div>
                  </div>
                  <div class="text-xs text-gray-400 whitespace-nowrap">${{ m.input_cost }}/M in &middot; ${{ m.output_cost }}/M out</div>
                  <div class="flex gap-1">
                    <button @click="startEditModel(m)" class="p-1.5 text-gray-400 hover:text-gray-200 transition-colors" title="Edit">
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" /><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 7.125l-2.652-2.652" /></svg>
                    </button>
                    <button @click="removeModel(m)" class="p-1.5 text-gray-400 hover:text-red-400 transition-colors" title="Delete">
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" /></svg>
                    </button>
                  </div>
                </div>
                <ModelEditForm v-if="editingModel && !isNewModel && editingModel.id === m.id" :model="editingModel" :is-new="false" @save="saveModelEdit" @cancel="cancelEdit" />
              </template>
            </div>
            <ModelEditForm v-if="editingModel && isNewModel && editingModel.provider === 'xai'" :model="editingModel" :is-new="true" @save="saveModelEdit" @cancel="cancelEdit" />
          </section>

          <!-- Local LLM Models -->
          <section v-if="hasLocalUrl" class="bg-gray-900 border border-gray-800 rounded-lg">
            <div class="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
              <h2 class="text-sm font-semibold text-gray-200 uppercase tracking-wide">Local LLM Models</h2>
              <button @click="startAddModel('local')" class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs font-medium transition-colors">
                + Add
              </button>
            </div>
            <div v-if="localModels.length === 0" class="p-5 text-sm text-gray-500">
              No local models configured. Add models matching your server's available models.
              <br /><span class="text-xs text-gray-600">Model IDs must start with <code class="text-gray-400">local-</code> (e.g., <code class="text-gray-400">local-llama3.2</code>)</span>
            </div>
            <div v-else>
              <template v-for="(m, idx) in localModels" :key="m.id">
                <div
                  draggable="true"
                  @dragstart="onDragStart(idx, 'local')"
                  @dragover="onDragOver($event, idx, 'local')"
                  @dragleave="onDragLeave"
                  @drop="onDrop($event, idx, 'local')"
                  @dragend="onDragEnd"
                  class="px-5 py-3 flex items-center gap-4 cursor-grab active:cursor-grabbing border-t border-b border-transparent transition-colors"
                  :class="{ 'border-b border-gray-800': idx < localModels.length - 1 }"
                >
                  <svg class="w-4 h-4 text-gray-600 shrink-0" fill="currentColor" viewBox="0 0 24 24"><circle cx="9" cy="5" r="1.5"/><circle cx="15" cy="5" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="19" r="1.5"/><circle cx="15" cy="19" r="1.5"/></svg>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm font-medium text-gray-200 truncate">{{ m.name }}</div>
                    <div class="text-xs text-gray-500">{{ m.model_id }}</div>
                  </div>
                  <div class="text-xs text-gray-400 whitespace-nowrap">${{ m.input_cost }}/M in &middot; ${{ m.output_cost }}/M out</div>
                  <div class="flex gap-1">
                    <button @click="startEditModel(m)" class="p-1.5 text-gray-400 hover:text-gray-200 transition-colors" title="Edit">
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" /><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 7.125l-2.652-2.652" /></svg>
                    </button>
                    <button @click="removeModel(m)" class="p-1.5 text-gray-400 hover:text-red-400 transition-colors" title="Delete">
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" /></svg>
                    </button>
                  </div>
                </div>
                <ModelEditForm v-if="editingModel && !isNewModel && editingModel.id === m.id" :model="editingModel" :is-new="false" @save="saveModelEdit" @cancel="cancelEdit" />
              </template>
            </div>
            <ModelEditForm v-if="editingModel && isNewModel && editingModel.provider === 'local'" :model="editingModel" :is-new="true" @save="saveModelEdit" @cancel="cancelEdit" />
          </section>

        </div>
      </div>

    </div>
  </div>
</template>
