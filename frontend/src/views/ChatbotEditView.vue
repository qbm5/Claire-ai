<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { getChatbot, saveChatbot, deleteChatbot, reindexChatbot, getUploads, uploadFiles, deleteUpload } from '@/services/chatbotService'
import { onEvent } from '@/services/eventBus'
import { createChatBot, type ChatBot } from '@/models'
import { useModels, loadModels } from '@/composables/useModels'
import ModelSelectDropdown from '@/components/shared/ModelSelectDropdown.vue'
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/composables/useToast'

const { show: toast } = useToast()
const auth = useAuth()

const { models } = useModels()

const props = defineProps<{ id: string }>()
const router = useRouter()
const route = useRoute()

const bot = ref<ChatBot>(createChatBot())
const loading = ref(false)
const saving = ref(false)
const indexing = ref(false)
const indexResult = ref('')
const indexProgress = ref({ current: 0, total: 0 })
const uploadedFiles = ref<{ name: string; size: number }[]>([])
const pendingFiles = ref<File[]>([])
const uploading = ref(false)
const dragging = ref(false)
let cleanups: (() => void)[] = []

onMounted(async () => {
  await loadModels()
  if (route.query.new) {
    bot.value.id = props.id
  } else {
    loading.value = true
    const data = await getChatbot(props.id)
    if (data && !('error' in data)) bot.value = data as ChatBot
    loading.value = false
  }
  await loadUploads()

  cleanups.push(onEvent('index_progress', (data: any) => {
    if (data.chatbot_id !== props.id) return
    indexProgress.value = { current: data.current, total: data.total }
  }))

  cleanups.push(onEvent('index_complete', (data: any) => {
    if (data.chatbot_id !== props.id) return
    indexing.value = false
    indexResult.value = `Indexed ${data.count} chunks`
    indexProgress.value = { current: 0, total: 0 }
  }))

  cleanups.push(onEvent('index_error', (data: any) => {
    if (data.chatbot_id !== props.id) return
    indexing.value = false
    indexResult.value = `Error: ${data.error}`
    indexProgress.value = { current: 0, total: 0 }
  }))
})

onUnmounted(() => {
  cleanups.forEach(fn => fn())
})

async function save() {
  if (saving.value) return
  saving.value = true
  try {
    await saveChatbot(bot.value)
    await flushPendingUploads()
    toast('Chatbot saved', 'success')
  } catch (e: any) {
    toast(e.message || 'Failed to save chatbot', 'error')
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!confirm('Delete this chatbot?')) return
  await deleteChatbot(bot.value.id)
  router.push('/chatbots')
}

async function doIndex() {
  indexing.value = true
  indexResult.value = ''
  indexProgress.value = { current: 0, total: 0 }
  try {
    await saveChatbot(bot.value)
    await flushPendingUploads()
    const res = await reindexChatbot(bot.value.id)
    if (res.count === 0) {
      indexing.value = false
      indexResult.value = 'No documents found'
    }
    // Otherwise, progress/completion comes via SSE events
  } catch (e: any) {
    indexing.value = false
    indexResult.value = `Error: ${e.message}`
  }
}

async function loadUploads() {
  if (props.id) {
    uploadedFiles.value = await getUploads(props.id)
  }
}

function onDrop(e: DragEvent) {
  dragging.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length) pendingFiles.value.push(...files)
}

function onFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (files.length) pendingFiles.value.push(...files)
  input.value = ''
}

function removePending(idx: number) {
  pendingFiles.value.splice(idx, 1)
}

async function removeUploaded(name: string) {
  await deleteUpload(props.id, name)
  await loadUploads()
}

async function flushPendingUploads() {
  if (pendingFiles.value.length === 0) return
  uploading.value = true
  await uploadFiles(bot.value.id, pendingFiles.value)
  pendingFiles.value = []
  uploading.value = false
  await loadUploads()
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function addText() {
  bot.value.source_texts.push('')
}

function removeText(idx: number) {
  bot.value.source_texts.splice(idx, 1)
}
</script>

<template>
  <div class="flex h-full">
    <!-- Left Sidebar -->
    <div class="w-72 bg-gray-900 border-r border-gray-800 flex flex-col">
      <!-- Header -->
      <div class="p-4 border-b border-gray-800">
        <div class="flex items-center gap-3">
          <button @click="router.push('/chatbots')" class="text-gray-400 hover:text-gray-50 text-sm">&larr;</button>
          <h1 class="text-lg font-bold truncate">{{ route.query.new ? 'New Chatbot' : bot.name || 'Edit Chatbot' }}</h1>
        </div>
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
            <input v-model="bot.name" class="input-sm" />
          </div>

          <div>
            <label class="block text-xs text-gray-400 mb-1">Description</label>
            <textarea v-model="bot.description" rows="2" class="input-sm resize-y"></textarea>
          </div>

          <div>
            <label class="block text-xs text-gray-400 mb-1">Tag</label>
            <input v-model="bot.tag" class="input-sm" />
          </div>

          <div>
            <label class="block text-xs text-gray-400 mb-1">Model</label>
            <ModelSelectDropdown v-model="bot.model" :models="models" />
          </div>

          <div>
            <label class="block text-xs text-gray-400 mb-1">Source Type</label>
            <select v-model="bot.source_type" class="input-sm">
              <option value="filesystem">Filesystem</option>
              <option value="text">Text</option>
              <option value="upload">Upload</option>
              <option value="github">GitHub</option>
            </select>
          </div>

          <div class="flex items-center gap-2">
            <label class="text-xs text-gray-400">Enabled</label>
            <input type="checkbox" v-model="bot.is_enabled" />
          </div>
        </div>

        <!-- Source config (source-type-specific sidebar fields) -->
        <div class="p-4 border-b border-gray-800 space-y-3">
          <div class="text-xs text-gray-500 uppercase font-medium">Source Config</div>

          <!-- Filesystem -->
          <template v-if="bot.source_type === 'filesystem'">
            <div>
              <label class="block text-xs text-gray-400 mb-1">Source Folder</label>
              <input v-model="bot.source_folder" placeholder="/path/to/documents" class="input-sm" />
            </div>
          </template>

          <!-- GitHub -->
          <template v-if="bot.source_type === 'github'">
            <div>
              <label class="block text-xs text-gray-400 mb-1">Owner</label>
              <input v-model="bot.github_owner" placeholder="e.g. anthropics" class="input-sm" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">Repo</label>
              <input v-model="bot.github_repo" placeholder="e.g. claude-code" class="input-sm" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">Branch</label>
              <input v-model="bot.github_branch" placeholder="main" class="input-sm" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">Folder (optional)</label>
              <input v-model="bot.github_folder" placeholder="e.g. docs/" class="input-sm" />
            </div>
          </template>

          <!-- Upload / Text hints -->
          <p v-if="bot.source_type === 'upload'" class="text-xs text-gray-500">Manage files in the main panel.</p>
          <p v-if="bot.source_type === 'text'" class="text-xs text-gray-500">Edit source texts in the main panel.</p>
        </div>

        <!-- Index Status -->
        <div class="p-4">
          <div class="text-xs text-gray-500 uppercase font-medium mb-2">Indexing</div>
          <div v-if="indexing && indexProgress.total > 0" class="space-y-1">
            <div class="flex justify-between text-xs text-gray-400">
              <span>Embedding chunks...</span>
              <span>{{ indexProgress.current }} / {{ indexProgress.total }}</span>
            </div>
            <div class="w-full h-2 bg-gray-800 rounded-full overflow-hidden">
              <div
                class="h-full bg-green-500 rounded-full transition-all duration-300"
                :style="{ width: (indexProgress.current / indexProgress.total * 100) + '%' }"
              ></div>
            </div>
          </div>
          <div v-else-if="indexing" class="text-xs text-gray-400">Preparing documents...</div>
          <div v-else-if="indexResult" class="text-xs text-gray-400">{{ indexResult }}</div>
          <div v-else class="text-xs text-gray-600">Not indexed yet</div>
        </div>
      </template>
      </div><!-- /scrollable -->

      <!-- Actions -->
      <div class="p-3 border-t border-gray-800 space-y-2">
        <button v-if="auth.canEdit('chatbots')" @click="save" :disabled="saving" class="w-full px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors">
          {{ saving ? 'Saving...' : 'Save' }}
        </button>
        <button @click="doIndex" :disabled="indexing" class="w-full px-3 py-2 bg-green-600 hover:bg-green-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors">
          {{ indexing ? 'Indexing...' : 'Index Documents' }}
        </button>
        <button v-if="auth.canDelete('chatbots') && !route.query.new" @click="remove" class="w-full px-3 py-2 bg-red-900/40 hover:bg-red-900/60 text-red-400 rounded-lg text-sm font-medium transition-colors">
          Delete
        </button>
      </div>
    </div>

    <!-- Main Content -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <template v-if="!loading">
        <!-- Upload source -->
        <div v-if="bot.source_type === 'upload'" class="flex-1 overflow-auto p-6">
          <h2 class="text-lg font-bold text-blue-400 mb-4">Upload Files</h2>
          <div class="space-y-4 max-w-4xl">
            <div
              class="border-2 border-dashed rounded-lg p-12 text-center transition-colors cursor-pointer"
              :class="dragging ? 'border-blue-500 bg-blue-500/10' : 'border-gray-700 hover:border-gray-500'"
              @dragover.prevent="dragging = true"
              @dragleave.prevent="dragging = false"
              @drop.prevent="onDrop"
              @click="($refs.fileInput as HTMLInputElement).click()"
            >
              <input ref="fileInput" type="file" multiple class="hidden" @change="onFileSelect" />
              <svg class="w-10 h-10 text-gray-600 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
              <p class="text-gray-400 text-sm">Drop files here or click to browse</p>
              <p class="text-gray-600 text-xs mt-1">Supports .txt, .md, .py, .js, .ts, .json, .html, .css, .xml, .csv, .sql and more</p>
            </div>

            <div v-if="pendingFiles.length > 0">
              <p class="text-xs text-gray-400 mb-2">Pending upload ({{ pendingFiles.length }} files)</p>
              <div class="space-y-1">
                <div v-for="(file, idx) in pendingFiles" :key="'p-' + idx" class="flex items-center justify-between bg-gray-800 rounded px-3 py-1.5 text-sm">
                  <span class="text-gray-300 truncate">{{ file.name }}</span>
                  <div class="flex items-center gap-2 ml-2 shrink-0">
                    <span class="text-xs text-gray-500">{{ formatSize(file.size) }}</span>
                    <button @click="removePending(idx)" class="text-red-400 hover:text-red-300 text-xs">&times;</button>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="uploadedFiles.length > 0">
              <p class="text-xs text-gray-400 mb-2">Uploaded ({{ uploadedFiles.length }} files)</p>
              <div class="space-y-1">
                <div v-for="file in uploadedFiles" :key="file.name" class="flex items-center justify-between bg-gray-800/50 rounded px-3 py-1.5 text-sm">
                  <span class="text-gray-400 truncate">{{ file.name }}</span>
                  <div class="flex items-center gap-2 ml-2 shrink-0">
                    <span class="text-xs text-gray-500">{{ formatSize(file.size) }}</span>
                    <button @click="removeUploaded(file.name)" class="text-red-400 hover:text-red-300 text-xs">&times;</button>
                  </div>
                </div>
              </div>
            </div>

            <p v-if="uploading" class="text-xs text-blue-400">Uploading files...</p>
          </div>
        </div>

        <!-- Text source -->
        <div v-else-if="bot.source_type === 'text'" class="flex-1 overflow-auto p-6">
          <div class="flex items-center justify-between mb-4 max-w-4xl">
            <h2 class="text-lg font-bold text-blue-400">Source Texts</h2>
            <button @click="addText" class="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs font-medium transition-colors">+ Add Text</button>
          </div>
          <div class="space-y-3 max-w-4xl">
            <div v-for="(text, idx) in bot.source_texts" :key="idx" class="relative">
              <textarea v-model="bot.source_texts[idx]" rows="8" class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm font-mono focus:outline-none focus:border-blue-500 resize-y"></textarea>
              <button @click="removeText(idx)" class="absolute top-2 right-2 text-red-400 hover:text-red-300 text-sm px-1">&times;</button>
            </div>
            <div v-if="bot.source_texts.length === 0" class="text-gray-600 text-sm text-center py-12">
              No source texts yet. Click "+ Add Text" to add one.
            </div>
          </div>
        </div>

        <!-- Filesystem source -->
        <div v-else-if="bot.source_type === 'filesystem'" class="flex-1 flex items-center justify-center">
          <div class="text-center text-gray-500 space-y-2">
            <svg class="w-12 h-12 mx-auto text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
            </svg>
            <p class="text-sm">Filesystem source configured</p>
            <p class="text-xs text-gray-600">{{ bot.source_folder || 'No folder set' }}</p>
            <p class="text-xs text-gray-600">Click "Index Documents" to scan and index files.</p>
          </div>
        </div>

        <!-- GitHub source -->
        <div v-else-if="bot.source_type === 'github'" class="flex-1 flex items-center justify-center">
          <div class="text-center text-gray-500 space-y-2">
            <svg class="w-12 h-12 mx-auto text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
            </svg>
            <p class="text-sm">GitHub source configured</p>
            <p v-if="bot.github_owner && bot.github_repo" class="text-xs text-gray-600">{{ bot.github_owner }}/{{ bot.github_repo }}{{ bot.github_branch ? ` (${bot.github_branch})` : '' }}{{ bot.github_folder ? ` / ${bot.github_folder}` : '' }}</p>
            <p v-else class="text-xs text-gray-600">Configure owner and repo in the sidebar.</p>
            <p class="text-xs text-gray-600">Click "Index Documents" to fetch and index.</p>
          </div>
        </div>

        <!-- Fallback -->
        <div v-else class="flex-1 flex items-center justify-center text-gray-600 text-sm">
          Select a source type to get started.
        </div>
      </template>
    </div>
  </div>
</template>
