<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { deepClone } from '@/utils/clone'
import { getPipelines, deletePipeline, copyPipeline, savePipeline } from '@/services/pipelineService'
import { getTools, saveTool } from '@/services/toolService'
import { saveOrder } from '@/services/reorderService'
import { createPipeline, getUid, type AiPipeline, type AiTool } from '@/models'
import { useToast } from '@/composables/useToast'
import { useAuth } from '@/composables/useAuth'
import { validatePipelineImport, computeResourceStatus } from '@/services/importValidator'
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
const pipelines = ref<AiPipeline[]>([])
const search = ref('')
const loading = ref(true)
const fileInput = ref<HTMLInputElement>()
const showImportReview = ref(false)
const importData = ref<Record<string, any>>({})
const importResourceStatus = ref<{ status: 'new' | 'update' | 'exists'; existingVersion?: number; existingId?: string }>({ status: 'new' })
const importToolStatuses = ref<{ name: string; type: number; image_url?: string; status: 'new' | 'update' | 'exists'; existingVersion?: number }[]>([])
const existingToolsCache = ref<AiTool[]>([])
const showImportMenu = ref(false)
const showCommunityBrowser = ref(false)
const communityAvailable = ref(false)
const selectedTags = ref<string[]>([])
const displayList = ref<AiPipeline[]>([])
const viewMode = ref<'grid' | 'list'>(localStorage.getItem('view_pipelines') as 'grid' | 'list' || 'list')
watch(viewMode, v => localStorage.setItem('view_pipelines', v))
const allTags = computed(() => {
  const tags = new Set<string>()
  let hasNoTag = false
  for (const p of pipelines.value) {
    const parts = splitTags(p.tag || '')
    if (parts.length) parts.forEach(pt => tags.add(pt))
    else hasNoTag = true
  }
  const sorted = [...tags].sort((a, b) => a.localeCompare(b))
  if (hasNoTag) sorted.unshift(NO_TAG)
  return sorted
})

watch([pipelines, search, selectedTags], () => {
  const q = search.value.toLowerCase()
  const tags = selectedTags.value
  displayList.value = pipelines.value.filter(p => {
    if (tags.length > 0) {
      const itemTags = splitTags(p.tag || '')
      if (!itemTags.length && !tags.includes(NO_TAG)) return false
      if (itemTags.length && !itemTags.some(it => tags.includes(it))) return false
    }
    return p.name.toLowerCase().includes(q) || p.tag.toLowerCase().includes(q) || p.description.toLowerCase().includes(q)
  })
}, { immediate: true })

async function onDragEnd() {
  const newVisibleIds = new Set(displayList.value.map(i => i.id))
  const hidden = pipelines.value.filter(i => !newVisibleIds.has(i.id))
  pipelines.value = [...displayList.value, ...hidden]
  await saveOrder('pipelines', pipelines.value.map(i => i.id))
}

async function load() {
  loading.value = true
  pipelines.value = await getPipelines()
  loading.value = false
}

function newPipeline() {
  const pl = createPipeline()
  router.push(`/pipeline/${pl.id}?new=1`)
}

async function duplicate(pl: AiPipeline) {
  await copyPipeline(pl.id)
  await load()
}

async function remove(pl: AiPipeline) {
  if (confirm(`Delete "${pl.name}"?`)) {
    await deletePipeline(pl.id)
    await load()
  }
}

function importPipeline() {
  showImportMenu.value = false
  fileInput.value?.click()
}

function importFromCommunity() {
  showImportMenu.value = false
  showCommunityBrowser.value = true
}

async function onCommunityImport(data: Record<string, any>) {
  const validation = validatePipelineImport(data)
  if (!validation.valid) {
    const msgs = validation.errors.slice(0, 5).map(e => e.path ? `${e.path}: ${e.message}` : e.message)
    toast('Invalid pipeline data:\n' + msgs.join('\n'), 'error')
    return
  }
  importData.value = data
  importResourceStatus.value = computeResourceStatus(data.export_uid, data.export_version || 1, pipelines.value)
  existingToolsCache.value = await getTools()
  importToolStatuses.value = (data._tools || []).map((t: any) => {
    const s = computeToolStatus(t, existingToolsCache.value)
    return { name: t.name || 'Unnamed', type: t.type ?? 0, image_url: t.image_url || '', status: s.status, existingVersion: s.existingVersion, existingId: s.existingId }
  })
  showImportReview.value = true
}

function computeToolStatus(tool: any, existingTools: AiTool[]) {
  // Primary match: export_uid
  if (tool.export_uid) {
    const byUid = existingTools.find(t => t.export_uid === tool.export_uid)
    if (byUid) {
      const version = tool.export_version || 1
      if (version > (byUid.export_version || 0)) {
        return { status: 'update' as const, existingVersion: byUid.export_version || 0, existingId: byUid.id }
      }
      return { status: 'exists' as const, existingVersion: byUid.export_version || 0, existingId: byUid.id }
    }
  }
  // Fallback: match by name + type
  const byName = existingTools.find(t => t.name === tool.name && t.type === tool.type)
  if (byName) {
    return { status: 'exists' as const, existingVersion: byName.export_version || 0, existingId: byName.id }
  }
  return { status: 'new' as const }
}

async function onFileSelected(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    const text = await file.text()
    const data = JSON.parse(text)
    const validation = validatePipelineImport(data)
    if (!validation.valid) {
      const msgs = validation.errors.slice(0, 5).map(e => e.path ? `${e.path}: ${e.message}` : e.message)
      toast('Invalid pipeline file:\n' + msgs.join('\n'), 'error')
      return
    }
    importData.value = data

    // Compute pipeline status
    importResourceStatus.value = computeResourceStatus(data.export_uid, data.export_version || 1, pipelines.value)

    // Fetch existing tools and compute per-tool statuses
    existingToolsCache.value = await getTools()
    importToolStatuses.value = (data._tools || []).map((t: any) => {
      const s = computeToolStatus(t, existingToolsCache.value)
      return { name: t.name || 'Unnamed', type: t.type ?? 0, image_url: t.image_url || '', status: s.status, existingVersion: s.existingVersion, existingId: s.existingId }
    })

    showImportReview.value = true
  } catch (e: any) {
    toast(e.message || 'Failed to parse file', 'error')
  } finally {
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function onImportConfirm(overwriteResource: boolean, toolOverwrites: boolean[]) {
  try {
    const data: any = deepClone(importData.value)
    const existingTools = existingToolsCache.value

    // 1. Handle embedded tools using per-tool overwrite decisions
    const toolIdMap: Record<string, string> = {}
    if (Array.isArray(data._tools)) {
      for (let i = 0; i < data._tools.length; i++) {
        const tool = data._tools[i]
        const oldId = tool.id
        // Match by export_uid first, then fallback to name+type
        const existing = (tool.export_uid ? existingTools.find(t => t.export_uid === tool.export_uid) : undefined)
          || existingTools.find(t => t.name === tool.name && t.type === tool.type)
        const shouldOverwrite = toolOverwrites[i] ?? false

        if (existing && !shouldOverwrite) {
          // skip, map to existing ID
          if (oldId) toolIdMap[oldId] = existing.id
        } else if (existing && shouldOverwrite) {
          // overwrite existing
          tool.id = existing.id
          if (oldId) toolIdMap[oldId] = existing.id
          await saveTool(tool)
        } else {
          // new → create
          const newId = getUid()
          if (oldId) toolIdMap[oldId] = newId
          tool.id = newId
          await saveTool(tool)
        }
      }
    }

    // Strip export metadata
    delete data._export_type
    delete data._export_name
    delete data._export_description
    delete data._export_date
    delete data._pip_packages
    delete data._tools

    // Assign pipeline ID (new, update, or overwrite existing)
    const status = importResourceStatus.value.status
    if (status === 'update' || (status === 'exists' && overwriteResource)) {
      data.id = importResourceStatus.value.existingId
    } else {
      data.id = getUid()
    }

    // Remap step IDs so imported steps don't collide
    const idMap: Record<string, string> = {}
    for (const step of data.steps || []) {
      const newId = getUid()
      idMap[step.id] = newId
      step.id = newId
    }
    // Update all step ID references + remap tool IDs
    for (const step of data.steps || []) {
      step.next_steps = (step.next_steps || []).map((id: string) => idMap[id] || id)
      step.next_steps_true = (step.next_steps_true || []).map((id: string) => idMap[id] || id)
      step.next_steps_false = (step.next_steps_false || []).map((id: string) => idMap[id] || id)
      // Remap tool references
      if (step.tool_id && toolIdMap[step.tool_id]) {
        step.tool_id = toolIdMap[step.tool_id]
      }
      if (step.tool && step.tool.id && toolIdMap[step.tool.id]) {
        step.tool.id = toolIdMap[step.tool.id]
      }
    }
    // Remap edges
    for (const edge of data.edges || []) {
      edge.source = idMap[edge.source] || edge.source
      edge.target = idMap[edge.target] || edge.target
      if (edge.source_handle) {
        for (const [oldId, newId] of Object.entries(idMap)) {
          edge.source_handle = edge.source_handle.replace(oldId, newId)
        }
      }
      if (edge.target_handle) {
        for (const [oldId, newId] of Object.entries(idMap)) {
          edge.target_handle = edge.target_handle.replace(oldId, newId)
        }
      }
      edge.id = `${edge.source}_${edge.target}_${edge.source_handle || ''}_${edge.target_handle || ''}`
    }

    await savePipeline(data)
    pipelines.value = await getPipelines()
    const label = status === 'update' ? 'Updated' : status === 'exists' ? 'Overwrote' : 'Imported'
    toast(`${label} "${data.name}"`, 'success')
    router.push(`/pipeline/${data.id}`)
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
      <h1 class="text-2xl font-bold">Pipelines</h1>
      <div v-if="auth.canCreate('pipelines')" class="flex gap-2">
        <div class="relative">
          <button @click="communityAvailable ? showImportMenu = !showImportMenu : importPipeline()" class="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition-colors flex items-center gap-1">
            Import
            <svg v-if="communityAvailable" class="w-3 h-3 text-gray-400" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" /></svg>
          </button>
          <div v-if="showImportMenu" class="dropdown-panel" @click.stop>
            <button @click="importPipeline" class="w-full px-4 py-2.5 text-left text-sm text-gray-200 hover:bg-gray-700 transition-colors flex items-center gap-2">
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
        <button @click="newPipeline" class="btn-primary">
          + New Pipeline
        </button>
      </div>
      <input ref="fileInput" type="file" accept=".json" class="hidden" @change="onFileSelected" />
      <ImportReviewModal v-model="showImportReview" :data="importData" :resourceStatus="importResourceStatus" :toolStatuses="importToolStatuses" @confirm="onImportConfirm" />
      <CommunityBrowserModal v-model="showCommunityBrowser" resourceType="pipeline" @import="onCommunityImport" />
    </div>

    <div class="flex items-center gap-4 mb-4">
      <input
        v-model="search"
        placeholder="Search pipelines..."
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
    </div>

    <div v-if="loading" class="text-gray-400">Loading...</div>
    <div v-else-if="displayList.length === 0" class="text-gray-500 text-center py-12">No pipelines found.</div>

    <!-- Grid view -->
    <draggable
      v-else-if="viewMode === 'grid'"
      v-model="displayList"
      item-key="id"
      class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
      ghost-class="opacity-30"
      @end="onDragEnd"
    >
      <template #item="{ element: pl }">
        <div
          class="card-hover flex flex-col cursor-grab active:cursor-grabbing"
        >
          <div class="flex items-center gap-2 mb-2">
            <img v-if="pl.image_url" :src="pl.image_url" class="w-8 h-8 rounded object-cover shrink-0 bg-black" />
            <LetterAvatar v-else :letter="pl.name" :size="32" />
            <h3 class="font-semibold text-gray-50 truncate min-w-0">{{ pl.name }}</h3>
            <span v-if="pl.tag" class="text-xs px-2 py-0.5 bg-gray-800 rounded-full text-gray-400 shrink-0 ml-auto max-w-[120px] truncate" :title="pl.tag">{{ pl.tag }}</span>
          </div>
          <p class="text-sm text-gray-400 mb-4 line-clamp-2">{{ pl.description || 'No description' }}</p>
          <div class="text-xs text-gray-500 mb-3">
            {{ pl.steps?.length || 0 }} steps
          </div>
          <div class="flex gap-2 mt-auto">
            <router-link :to="`/pipeline-runner/${pl.id}`" class="px-3 py-1.5 bg-purple-600 text-white rounded-lg text-xs hover:bg-purple-700 transition-colors">
              Run
            </router-link>
            <router-link v-if="auth.canEdit('pipelines')" :to="`/pipeline/${pl.id}`" class="btn-sm-ghost">
              Edit
            </router-link>
            <button v-if="auth.canCreate('pipelines')" @click="duplicate(pl)" class="px-3 py-1.5 bg-gray-800 text-gray-300 rounded-lg text-xs hover:bg-gray-700 transition-colors">
              Copy
            </button>
            <button v-if="auth.canDelete('pipelines')" @click="remove(pl)" class="btn-sm-danger-ghost ml-auto">
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
      <template #item="{ element: pl }">
        <div class="flex items-center gap-3 px-3 py-2.5 hover:bg-gray-800/30 transition-colors cursor-grab active:cursor-grabbing">
          <svg class="w-3.5 h-3.5 text-gray-700 shrink-0" viewBox="0 0 16 16" fill="currentColor"><circle cx="5" cy="3" r="1.5"/><circle cx="11" cy="3" r="1.5"/><circle cx="5" cy="8" r="1.5"/><circle cx="11" cy="8" r="1.5"/><circle cx="5" cy="13" r="1.5"/><circle cx="11" cy="13" r="1.5"/></svg>
          <img v-if="pl.image_url" :src="pl.image_url" class="w-6 h-6 rounded object-cover shrink-0 bg-black" />
          <LetterAvatar v-else :letter="pl.name" :size="24" />
          <span :title="pl.name" class="font-medium text-sm text-gray-50 truncate min-w-[150px] max-w-[150px]">{{ pl.name }}</span>
          <span :title="pl.description" class="text-sm text-gray-500 truncate flex-1 hidden sm:inline">{{ pl.description || 'No description' }}</span>
          <span v-if="pl.tag" class="text-xs px-2 py-0.5 bg-gray-800 rounded-full text-gray-400 shrink-0 hidden md:inline">{{ pl.tag }}</span>
          <span class="text-xs text-gray-600 shrink-0 hidden md:inline">{{ pl.steps?.length || 0 }} steps</span>
          <div class="flex gap-1 shrink-0 ml-auto">
            <router-link :to="`/pipeline-runner/${pl.id}`" class="px-2 py-1 bg-purple-600 text-white rounded text-xs hover:bg-purple-700 transition-colors">Run</router-link>
            <router-link v-if="auth.canEdit('pipelines')" :to="`/pipeline/${pl.id}`" class="btn-sm-outline">Edit</router-link>
            <button v-if="auth.canCreate('pipelines')" @click="duplicate(pl)" class="px-2 py-1 text-gray-400 rounded text-xs hover:bg-gray-700 transition-colors">Copy</button>
            <button v-if="auth.canDelete('pipelines')" @click="remove(pl)" class="btn-sm-danger">Del</button>
          </div>
        </div>
      </template>
    </draggable>
  </div>
</template>
