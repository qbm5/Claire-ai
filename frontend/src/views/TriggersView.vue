<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { deepClone } from '@/utils/clone'
import { getTriggers, deleteTrigger, fireTrigger, saveTrigger } from '@/services/triggerService'
import { saveOrder } from '@/services/reorderService'
import { createTrigger, TriggerTypeLabels, TriggerType, getUid, type AiTrigger } from '@/models'
import { useToast } from '@/composables/useToast'
import { useAuth } from '@/composables/useAuth'
import { validateTriggerImport, computeResourceStatus } from '@/services/importValidator'
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
const triggers = ref<AiTrigger[]>([])
const search = ref('')
const loading = ref(true)
const fileInput = ref<HTMLInputElement>()
const showImportReview = ref(false)
const importData = ref<Record<string, any>>({})
const importResourceStatus = ref<{ status: 'new' | 'update' | 'exists'; existingVersion?: number; existingId?: string }>({ status: 'new' })
const showImportMenu = ref(false)
const showCommunityBrowser = ref(false)
const communityAvailable = ref(false)
const showDisabled = ref(true)
const selectedTags = ref<string[]>([])
const displayList = ref<AiTrigger[]>([])
const viewMode = ref<'grid' | 'list'>(localStorage.getItem('view_triggers') as 'grid' | 'list' || 'list')
watch(viewMode, v => localStorage.setItem('view_triggers', v))
const allTags = computed(() => {
  const tags = new Set<string>()
  let hasNoTag = false
  for (const t of triggers.value) {
    const parts = splitTags(t.tag || '')
    if (parts.length) parts.forEach(p => tags.add(p))
    else hasNoTag = true
  }
  const sorted = [...tags].sort((a, b) => a.localeCompare(b))
  if (hasNoTag) sorted.unshift(NO_TAG)
  return sorted
})

watch([triggers, search, showDisabled, selectedTags], () => {
  const q = search.value.toLowerCase()
  const tags = selectedTags.value
  displayList.value = triggers.value.filter(t => {
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
  [TriggerType.Cron]: 'bg-blue-600/20 text-blue-400',
  [TriggerType.FileWatcher]: 'bg-green-600/20 text-green-400',
  [TriggerType.Webhook]: 'bg-purple-600/20 text-purple-400',
  [TriggerType.RSS]: 'bg-orange-600/20 text-orange-400',
  [TriggerType.Custom]: 'bg-cyan-600/20 text-cyan-400',
}

async function onDragEnd() {
  const newVisibleIds = new Set(displayList.value.map(i => i.id))
  const hidden = triggers.value.filter(i => !newVisibleIds.has(i.id))
  triggers.value = [...displayList.value, ...hidden]
  await saveOrder('triggers', triggers.value.map(i => i.id))
}

async function load() {
  loading.value = true
  triggers.value = await getTriggers()
  loading.value = false
}

function newTrigger() {
  const trigger = createTrigger()
  router.push(`/trigger/${trigger.id}?new=1`)
}

async function remove(trigger: AiTrigger) {
  if (confirm(`Delete "${trigger.name}"?`)) {
    await deleteTrigger(trigger.id)
    await load()
  }
}

async function fire(trigger: AiTrigger) {
  try {
    await fireTrigger(trigger.id)
    toast(`Fired "${trigger.name}"`, 'success')
    await load()
  } catch (e: any) {
    toast(e.message || 'Fire failed', 'error')
  }
}

function importTrigger() {
  showImportMenu.value = false
  fileInput.value?.click()
}

function importFromCommunity() {
  showImportMenu.value = false
  showCommunityBrowser.value = true
}

function onCommunityImport(data: Record<string, any>) {
  const validation = validateTriggerImport(data)
  if (!validation.valid) {
    const msgs = validation.errors.slice(0, 5).map(e => e.path ? `${e.path}: ${e.message}` : e.message)
    toast('Invalid trigger data:\n' + msgs.join('\n'), 'error')
    return
  }
  importData.value = data
  importResourceStatus.value = computeResourceStatus(data.export_uid, data.export_version || 1, triggers.value)
  showImportReview.value = true
}

async function onFileSelected(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    const text = await file.text()
    const data = JSON.parse(text)
    const validation = validateTriggerImport(data)
    if (!validation.valid) {
      const msgs = validation.errors.slice(0, 5).map(e => e.path ? `${e.path}: ${e.message}` : e.message)
      toast('Invalid trigger file:\n' + msgs.join('\n'), 'error')
      return
    }
    importData.value = data
    importResourceStatus.value = computeResourceStatus(data.export_uid, data.export_version || 1, triggers.value)
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
    await saveTrigger(data as AiTrigger)
    triggers.value = await getTriggers()
    const label = status === 'update' ? 'Updated' : status === 'exists' ? 'Overwrote' : 'Imported'
    toast(`${label} "${data.name}"`, 'success')
    router.push(`/trigger/${data.id}`)
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
      <h1 class="text-2xl font-bold">Triggers</h1>
      <div v-if="auth.canCreate('triggers')" class="flex gap-2">
        <div class="relative">
          <button @click="communityAvailable ? showImportMenu = !showImportMenu : importTrigger()" class="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition-colors flex items-center gap-1">
            Import
            <svg v-if="communityAvailable" class="w-3 h-3 text-gray-400" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" /></svg>
          </button>
          <div v-if="showImportMenu" class="dropdown-panel" @click.stop>
            <button @click="importTrigger" class="w-full px-4 py-2.5 text-left text-sm text-gray-200 hover:bg-gray-700 transition-colors flex items-center gap-2">
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
        <button @click="newTrigger" class="btn-primary">
          + New Trigger
        </button>
      </div>
      <input ref="fileInput" type="file" accept=".json" class="hidden" @change="onFileSelected" />
      <ImportReviewModal v-model="showImportReview" :data="importData" :resourceStatus="importResourceStatus" @confirm="onImportConfirm" />
      <CommunityBrowserModal v-model="showCommunityBrowser" resourceType="trigger" @import="onCommunityImport" />
    </div>

    <div class="flex items-center gap-4 mb-4">
      <input
        v-model="search"
        placeholder="Search triggers..."
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
    <div v-else-if="displayList.length === 0" class="text-gray-500 text-center py-12">No triggers found.</div>

    <!-- Grid view -->
    <draggable
      v-else-if="viewMode === 'grid'"
      v-model="displayList"
      item-key="id"
      class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
      ghost-class="opacity-30"
      @end="onDragEnd"
    >
      <template #item="{ element: trigger }">
        <div
          class="card-hover flex flex-col cursor-grab active:cursor-grabbing"
        >
          <div class="flex items-center gap-2 mb-2">
            <img v-if="trigger.image_url" :src="trigger.image_url" class="w-8 h-8 rounded object-cover shrink-0 bg-black" />
            <LetterAvatar v-else :letter="trigger.name" :size="32" />
            <h3 class="font-semibold text-gray-50 truncate min-w-0">{{ trigger.name }}</h3>
            <span class="text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ml-auto max-w-[120px] truncate" :class="typeColor[trigger.trigger_type] || 'bg-gray-700 text-gray-300'">
              {{ TriggerTypeLabels[trigger.trigger_type as TriggerType] || 'Unknown' }}
            </span>
          </div>
          <p class="text-sm text-gray-400 mb-3 line-clamp-2">{{ trigger.description || 'No description' }}</p>

          <!-- Status line -->
          <div class="flex items-center gap-3 text-xs text-gray-500 mb-3">
            <span class="flex items-center gap-1">
              <span class="w-1.5 h-1.5 rounded-full" :class="trigger.is_enabled ? 'bg-green-400' : 'bg-gray-600'"></span>
              {{ trigger.is_enabled ? 'Enabled' : 'Disabled' }}
            </span>
            <span v-if="trigger.fire_count">{{ trigger.fire_count }} fires</span>
            <span v-if="trigger.last_status" :class="trigger.last_status === 'OK' ? 'text-green-500' : 'text-red-400'">
              {{ trigger.last_status }}
            </span>
          </div>

          <div class="text-xs text-gray-500 mb-3">
            <span v-if="trigger.tag">{{ trigger.tag }}</span>
            <span v-else>&nbsp;</span>
          </div>
          <div class="flex gap-2 mt-auto">
            <router-link v-if="auth.canEdit('triggers')" :to="`/trigger/${trigger.id}`" class="btn-sm-ghost">
              Edit
            </router-link>
            <button v-if="trigger.trigger_type !== TriggerType.Custom" @click="fire(trigger)" class="px-3 py-1.5 bg-purple-600/20 text-purple-400 rounded-lg text-xs hover:bg-purple-600/30 transition-colors">
              Fire
            </button>
            <button v-if="auth.canDelete('triggers')" @click="remove(trigger)" class="btn-sm-danger-ghost ml-auto">
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
      <template #item="{ element: trigger }">
        <div class="flex items-center gap-3 px-3 py-2.5 hover:bg-gray-800/30 transition-colors cursor-grab active:cursor-grabbing">
          <svg class="w-3.5 h-3.5 text-gray-700 shrink-0" viewBox="0 0 16 16" fill="currentColor"><circle cx="5" cy="3" r="1.5"/><circle cx="11" cy="3" r="1.5"/><circle cx="5" cy="8" r="1.5"/><circle cx="11" cy="8" r="1.5"/><circle cx="5" cy="13" r="1.5"/><circle cx="11" cy="13" r="1.5"/></svg>
          <img v-if="trigger.image_url" :src="trigger.image_url" class="w-6 h-6 rounded object-cover shrink-0 bg-black" />
          <LetterAvatar v-else :letter="trigger.name" :size="24" />
          <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="trigger.is_enabled ? 'bg-green-400' : 'bg-gray-600'"></span>
          <span class="font-medium text-sm truncate min-w-[120px] max-w-[200px]" :class="trigger.is_enabled ? 'text-gray-50' : 'text-gray-500'">{{ trigger.name }}</span>
          <span class="text-xs px-2 py-0.5 rounded-full font-medium shrink-0" :class="typeColor[trigger.trigger_type] || 'bg-gray-700 text-gray-300'">
            {{ TriggerTypeLabels[trigger.trigger_type as TriggerType] || '?' }}
          </span>
          <span class="text-sm text-gray-500 truncate flex-1 hidden sm:inline">{{ trigger.description || 'No description' }}</span>
          <span v-if="trigger.fire_count" class="text-xs text-gray-600 shrink-0 hidden md:inline">{{ trigger.fire_count }} fires</span>
          <span v-if="trigger.last_status" class="text-xs shrink-0 hidden md:inline" :class="trigger.last_status === 'OK' ? 'text-green-500' : 'text-red-400'">{{ trigger.last_status }}</span>
          <div class="flex gap-1 shrink-0 ml-auto">
            <router-link v-if="auth.canEdit('triggers')" :to="`/trigger/${trigger.id}`" class="btn-sm-outline">Edit</router-link>
            <button v-if="trigger.trigger_type !== TriggerType.Custom" @click="fire(trigger)" class="px-2 py-1 text-purple-400 rounded text-xs hover:bg-purple-600/20 transition-colors">Fire</button>
            <button v-if="auth.canDelete('triggers')" @click="remove(trigger)" class="btn-sm-danger">Del</button>
          </div>
        </div>
      </template>
    </draggable>
  </div>
</template>
