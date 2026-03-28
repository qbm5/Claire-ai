<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { deepClone } from '@/utils/clone'
import { getTools, deleteTool, saveTool } from '@/services/toolService'
import { saveOrder } from '@/services/reorderService'
import { createTool, ToolTypeLabels, ToolType, getUid, type AiTool } from '@/models'
import { useToast } from '@/composables/useToast'
import { useAuth } from '@/composables/useAuth'
import { validateToolImport, computeResourceStatus } from '@/services/importValidator'
import { getCommunityStatus } from '@/services/communityService'
import ImportReviewModal from '@/components/shared/ImportReviewModal.vue'
import CommunityBrowserModal from '@/components/shared/CommunityBrowserModal.vue'
import TagFilterDropdown from '@/components/shared/TagFilterDropdown.vue'
import LetterAvatar from '@/components/shared/LetterAvatar.vue'
import { NO_TAG, splitTags } from '@/utils/tags'
import draggable from 'vuedraggable'

const { show: toast } = useToast()
const auth = useAuth()
const router = useRouter()
const tools = ref<AiTool[]>([])
const search = ref('')
const loading = ref(true)
const fileInput = ref<HTMLInputElement>()
const showImportReview = ref(false)
const importData = ref<Record<string, any>>({})
const importResourceStatus = ref<{ status: 'new' | 'update' | 'exists'; existingVersion?: number; existingId?: string }>({ status: 'new' })
const showImportMenu = ref(false)
const showCommunityBrowser = ref(false)
const communityAvailable = ref(false)
const showDisabled = ref(false)
const selectedTags = ref<string[]>([])
const displayList = ref<AiTool[]>([])
const viewMode = ref<'grid' | 'list'>(localStorage.getItem('view_tools') as 'grid' | 'list' || 'list')
watch(viewMode, v => localStorage.setItem('view_tools', v))
const allTags = computed(() => {
  const tags = new Set<string>()
  let hasNoTag = false
  for (const t of tools.value) {
    const parts = splitTags(t.tag || '')
    if (parts.length) parts.forEach(p => tags.add(p))
    else hasNoTag = true
  }
  const sorted = [...tags].sort((a, b) => a.localeCompare(b))
  if (hasNoTag) sorted.unshift(NO_TAG)
  return sorted
})

watch([tools, search, showDisabled, selectedTags], () => {
  const q = search.value.toLowerCase()
  const tags = selectedTags.value
  displayList.value = tools.value.filter(t => {
    if (!showDisabled.value && !t.is_enabled) return false
    if (tags.length > 0) {
      const itemTags = splitTags(t.tag || '')
      if (!itemTags.length && !tags.includes(NO_TAG)) return false
      if (itemTags.length && !itemTags.some(it => tags.includes(it))) return false
    }
    return t.name.toLowerCase().includes(q) || t.tag.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)
  })
}, { immediate: true })

const typeColor: Record<number, string> = {
  0: 'bg-purple-600/20 text-purple-400',  // LLM
  1: 'bg-green-600/20 text-green-400',    // Endpoint
  2: 'bg-yellow-600/20 text-yellow-400',  // Pause
  3: 'bg-orange-600/20 text-orange-400',  // Agent
  4: 'bg-blue-600/20 text-blue-400',      // Pipeline
  5: 'bg-cyan-600/20 text-cyan-400',      // If
  6: 'bg-pink-600/20 text-pink-400',      // Parallel
  7: 'bg-gray-600/20 text-gray-400',      // End
  8: 'bg-amber-600/20 text-amber-400',    // Wait
  9: 'bg-emerald-600/20 text-emerald-400', // Start
}

// Only runnable tool types (LLM, Endpoint, Agent)
const runnableTypes = new Set([ToolType.LLM, ToolType.Endpoint, ToolType.Agent])

async function onDragEnd() {
  const newVisibleIds = new Set(displayList.value.map(i => i.id))
  const hidden = tools.value.filter(i => !newVisibleIds.has(i.id))
  tools.value = [...displayList.value, ...hidden]
  await saveOrder('tools', tools.value.map(i => i.id))
}

async function load() {
  loading.value = true
  tools.value = await getTools()
  loading.value = false
}

function newTool() {
  const tool = createTool()
  router.push(`/tool/${tool.id}?new=1`)
}

async function remove(tool: AiTool) {
  if (confirm(`Delete "${tool.name}"?`)) {
    await deleteTool(tool.id)
    await load()
  }
}

function importTool() {
  showImportMenu.value = false
  fileInput.value?.click()
}

function importFromCommunity() {
  showImportMenu.value = false
  showCommunityBrowser.value = true
}

function onCommunityImport(data: Record<string, any>) {
  const validation = validateToolImport(data)
  if (!validation.valid) {
    const msgs = validation.errors.slice(0, 5).map(e => e.path ? `${e.path}: ${e.message}` : e.message)
    toast('Invalid tool data:\n' + msgs.join('\n'), 'error')
    return
  }
  importData.value = data
  importResourceStatus.value = computeResourceStatus(data.export_uid, data.export_version || 1, tools.value)
  showImportReview.value = true
}

async function onFileSelected(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    const text = await file.text()
    const data = JSON.parse(text)
    const validation = validateToolImport(data)
    if (!validation.valid) {
      const msgs = validation.errors.slice(0, 5).map(e => e.path ? `${e.path}: ${e.message}` : e.message)
      toast('Invalid tool file:\n' + msgs.join('\n'), 'error')
      return
    }
    importData.value = data
    importResourceStatus.value = computeResourceStatus(data.export_uid, data.export_version || 1, tools.value)
    showImportReview.value = true
  } catch (e: any) {
    toast(e.message || 'Failed to parse file', 'error')
  } finally {
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function onImportConfirm(overwriteResource: boolean, _toolOverwrites: boolean[]) {
  try {
    const data = deepClone(importData.value)
    delete data._export_type
    delete data._export_name
    delete data._export_description
    delete data._export_date
    delete data._pip_packages
    const status = importResourceStatus.value.status
    if (status === 'update' || (status === 'exists' && overwriteResource)) {
      data.id = importResourceStatus.value.existingId
    } else {
      data.id = getUid()
    }
    await saveTool(data as AiTool)
    tools.value = await getTools()
    const label = status === 'update' ? 'Updated' : status === 'exists' ? 'Overwrote' : 'Imported'
    toast(`${label} "${data.name}"`, 'success')
    router.push(`/tool/${data.id}`)
  } catch (e: any) {
    toast(e.message || 'Failed to import', 'error')
  }
}

onMounted(async () => {
  load()
  try {
    const status = await getCommunityStatus()
    communityAvailable.value = status.configured && status.reachable
  } catch { /* ignore */ }
})
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold">Tools</h1>
      <div v-if="auth.canCreate('tools')" class="flex gap-2">
        <div class="relative">
          <button @click="communityAvailable ? showImportMenu = !showImportMenu : importTool()" class="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition-colors flex items-center gap-1">
            Import
            <svg v-if="communityAvailable" class="w-3 h-3 text-gray-400" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" /></svg>
          </button>
          <div v-if="showImportMenu" class="dropdown-panel" @click.stop>
            <button @click="importTool" class="w-full px-4 py-2.5 text-left text-sm text-gray-200 hover:bg-gray-700 transition-colors flex items-center gap-2">
              <svg class="w-4 h-4 text-gray-400" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM6.293 6.707a1 1 0 010-1.414l3-3a1 1 0 011.414 0l3 3a1 1 0 01-1.414 1.414L11 5.414V13a1 1 0 11-2 0V5.414L7.707 6.707a1 1 0 01-1.414 0z" clip-rule="evenodd" /></svg>
              From File
            </button>
            <button @click="importFromCommunity" class="w-full px-4 py-2.5 text-left text-sm text-gray-200 hover:bg-gray-700 transition-colors flex items-center gap-2">
              <svg class="w-4 h-4 text-gray-400" viewBox="0 0 20 20" fill="currentColor"><path d="M13 6a3 3 0 11-6 0 3 3 0 016 0zM18 8a2 2 0 11-4 0 2 2 0 014 0zM14 15a4 4 0 00-8 0v3h8v-3zM6 8a2 2 0 11-4 0 2 2 0 014 0zM16 18v-3a5.972 5.972 0 00-.75-2.906A3.005 3.005 0 0119 15v3h-3zM4.75 12.094A5.973 5.973 0 004 15v3H1v-3a3 3 0 013.75-2.906z" /></svg>
              From Community
            </button>
          </div>
          <div v-if="showImportMenu" class="fixed inset-0 z-10" @click="showImportMenu = false" />
        </div>
        <button @click="newTool" class="btn-primary">
          + New Tool
        </button>
      </div>
      <input ref="fileInput" type="file" accept=".json" class="hidden" @change="onFileSelected" />
      <ImportReviewModal v-model="showImportReview" :data="importData" :resourceStatus="importResourceStatus" @confirm="onImportConfirm" />
      <CommunityBrowserModal v-model="showCommunityBrowser" resourceType="tool" @import="onCommunityImport" />
    </div>

    <div class="flex items-center gap-4 mb-4">
      <input
        v-model="search"
        placeholder="Search tools..."
        class="input-search"
      />
      <TagFilterDropdown v-model="selectedTags" :tags="allTags" />
      <div class="flex items-center gap-1 bg-gray-800 rounded-lg p-0.5 shrink-0">
        <button @click="viewMode = 'grid'" class="p-1.5 rounded transition-colors" :class="viewMode === 'grid' ? 'bg-gray-600 text-gray-50' : 'text-gray-500 hover:text-gray-300'">
          <svg class="w-4 h-4" viewBox="0 0 16 16" fill="currentColor"><rect x="1" y="1" width="6" height="6" rx="1"/><rect x="9" y="1" width="6" height="6" rx="1"/><rect x="1" y="9" width="6" height="6" rx="1"/><rect x="9" y="9" width="6" height="6" rx="1"/></svg>
        </button>
        <button @click="viewMode = 'list'" class="p-1.5 rounded transition-colors" :class="viewMode === 'list' ? 'bg-gray-600 text-gray-50' : 'text-gray-500 hover:text-gray-300'">
          <svg class="w-4 h-4" viewBox="0 0 16 16" fill="currentColor"><rect x="1" y="2" width="14" height="2" rx="0.5"/><rect x="1" y="7" width="14" height="2" rx="0.5"/><rect x="1" y="12" width="14" height="2" rx="0.5"/></svg>
        </button>
      </div>
      <label class="flex items-center gap-2 text-sm text-gray-400 cursor-pointer select-none whitespace-nowrap">
        <input type="checkbox" v-model="showDisabled" class="accent-blue-500" />
        Show disabled
      </label>
    </div>

    <div v-if="loading" class="text-gray-400">Loading...</div>
    <div v-else-if="displayList.length === 0" class="text-gray-500 text-center py-12">No tools found.</div>

    <!-- Grid view -->
    <draggable
      v-else-if="viewMode === 'grid'"
      v-model="displayList"
      item-key="id"
      class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
      ghost-class="opacity-30"
      @end="onDragEnd"
    >
      <template #item="{ element: tool }">
        <div
          class="card-hover flex flex-col cursor-grab active:cursor-grabbing"
        >
          <div class="flex items-center gap-2 mb-2">
            <img v-if="tool.image_url" :src="tool.image_url" class="w-8 h-8 rounded object-cover shrink-0 bg-black" />
            <LetterAvatar v-else :letter="tool.name" :size="32" />
            <span v-if="!tool.is_enabled" class="w-1.5 h-1.5 rounded-full bg-gray-600 shrink-0" title="Disabled"></span>
            <h3 class="font-semibold text-gray-50 truncate min-w-0" :class="{ 'text-gray-500': !tool.is_enabled }">{{ tool.name }}</h3>
            <span class="text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ml-auto max-w-[120px] truncate" :class="typeColor[tool.type] || 'bg-gray-700 text-gray-300'">
              {{ ToolTypeLabels[tool.type as ToolType] || 'Unknown' }}
            </span>
          </div>
          <p class="text-sm text-gray-400 mb-4 line-clamp-2">{{ tool.description || 'No description' }}</p>
          <div class="text-xs text-gray-500 mb-3">
            <span v-if="tool.tag">{{ tool.tag }}</span>
            <span v-else>&nbsp;</span>
          </div>
          <div class="flex gap-2 mt-auto">
            <router-link
              v-if="runnableTypes.has(tool.type)"
              :to="`/tool-runner/${tool.id}`"
              class="px-3 py-1.5 bg-purple-600 text-white rounded-lg text-xs hover:bg-purple-700 transition-colors"
            >
              Run
            </router-link>
            <router-link v-if="auth.canEdit('tools')" :to="`/tool/${tool.id}`" class="btn-sm-ghost">
              Edit
            </router-link>
            <button v-if="auth.canDelete('tools')" @click="remove(tool)" class="btn-sm-danger-ghost ml-auto">
              Delete
            </button>
          </div>
        </div>
      </template>
    </draggable>

    <!-- List view -->
    <draggable
      v-else
      v-model="displayList"
      item-key="id"
      class="border border-gray-800 rounded-lg overflow-hidden divide-y divide-gray-800/50"
      ghost-class="opacity-30"
      @end="onDragEnd"
    >
      <template #item="{ element: tool }">
        <div class="flex items-center gap-3 px-3 py-2.5 hover:bg-gray-800/30 transition-colors cursor-grab active:cursor-grabbing">
          <svg class="w-3.5 h-3.5 text-gray-700 shrink-0" viewBox="0 0 16 16" fill="currentColor"><circle cx="5" cy="3" r="1.5"/><circle cx="11" cy="3" r="1.5"/><circle cx="5" cy="8" r="1.5"/><circle cx="11" cy="8" r="1.5"/><circle cx="5" cy="13" r="1.5"/><circle cx="11" cy="13" r="1.5"/></svg>
          <img v-if="tool.image_url" :src="tool.image_url" class="w-6 h-6 rounded object-cover shrink-0 bg-black" />
          <LetterAvatar v-else :letter="tool.name" :size="24" />
          <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="tool.is_enabled ? 'bg-green-400' : 'bg-gray-600'"></span>
          <span class="font-medium text-sm truncate min-w-[120px] max-w-[200px]" :class="tool.is_enabled ? 'text-gray-50' : 'text-gray-500'">{{ tool.name }}</span>
          <span class="text-xs px-2 py-0.5 rounded-full font-medium shrink-0" :class="typeColor[tool.type] || 'bg-gray-700 text-gray-300'">
            {{ ToolTypeLabels[tool.type as ToolType] || '?' }}
          </span>
          <span class="text-sm text-gray-500 truncate flex-1 hidden sm:inline">{{ tool.description || 'No description' }}</span>
          <span v-if="tool.tag" class="text-xs text-gray-600 shrink-0 hidden md:inline">{{ tool.tag }}</span>
          <div class="flex gap-1 shrink-0 ml-auto">
            <router-link v-if="runnableTypes.has(tool.type)" :to="`/tool-runner/${tool.id}`" class="px-2 py-1 bg-purple-600 text-white rounded text-xs hover:bg-purple-700 transition-colors">Run</router-link>
            <router-link v-if="auth.canEdit('tools')" :to="`/tool/${tool.id}`" class="btn-sm-outline">Edit</router-link>
            <button v-if="auth.canDelete('tools')" @click="remove(tool)" class="btn-sm-danger">Del</button>
          </div>
        </div>
      </template>
    </draggable>

  </div>
</template>
