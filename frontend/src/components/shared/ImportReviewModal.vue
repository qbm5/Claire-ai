<script setup lang="ts">
import { ref, computed, watch, markRaw } from 'vue'
import { VueFlow, type Node, type Edge, type VueFlowStore } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { PathFindingEdge } from '@vue-flow/pathfinding-edge'
import StepNode from '@/components/pipeline/StepNode.vue'
import { ToolTypeLabels, type ToolType } from '@/models'
import LetterAvatar from '@/components/shared/LetterAvatar.vue'

export interface ResourceImportStatus {
  status: 'new' | 'update' | 'exists'
  existingVersion?: number
  existingId?: string
}

export interface ToolImportStatus {
  name: string
  type: number
  image_url?: string
  status: 'new' | 'update' | 'exists'
  existingVersion?: number
  existingId?: string
}

const props = defineProps<{
  modelValue: boolean
  data: Record<string, any>
  resourceStatus?: ResourceImportStatus
  toolStatuses?: ToolImportStatus[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'confirm': [overwriteResource: boolean, toolOverwrites: boolean[]]
}>()

const overwriteResource = ref(false)
const toolOverwrites = ref<boolean[]>([])
const flowKey = ref(0)

const nodeTypes: any = { step: markRaw(StepNode) }
const edgeTypes: any = { pathfinding: markRaw(PathFindingEdge) }

watch(() => props.modelValue, (open) => {
  if (open) {
    overwriteResource.value = false
    toolOverwrites.value = toolItems.value.map(t => t.status === 'update')
    // Force VueFlow remount so it gets fresh container dimensions
    flowKey.value++
  }
})

function onPaneReady(instance: VueFlowStore) {
  setTimeout(() => instance.fitView({ padding: 0.2 }), 100)
}

const exportName = computed(() => props.data?._export_name || props.data?.name || 'Unnamed')
const exportDescription = computed(() => props.data?._export_description || props.data?.description || '')
const exportDate = computed(() => {
  const d = props.data?._export_date
  if (!d) return ''
  try { return new Date(d).toLocaleString() } catch { return d }
})
const exportType = computed(() => props.data?._export_type || 'unknown')
const exportVersion = computed(() => props.data?.export_version || null)
const pipPackages = computed<string[]>(() => props.data?._pip_packages || [])
const isPipeline = computed(() => exportType.value === 'pipeline')

const toolItems = computed<{ name: string; type: number; image_url?: string; status: 'new' | 'update' | 'exists'; existingVersion?: number }[]>(() => {
  if (props.toolStatuses) return props.toolStatuses
  return (props.data?._tools || []).map((t: any) => ({
    name: t.name || 'Unnamed',
    type: t.type ?? 0,
    image_url: t.image_url || '',
    status: 'new' as const,
  }))
})

const status = computed(() => props.resourceStatus?.status || 'new')
const canImport = computed(() => {
  if (status.value === 'exists') return overwriteResource.value
  return true
})

const statusLabel = computed(() => {
  const s = props.resourceStatus
  if (!s || s.status === 'new') return null
  if (s.status === 'exists') return `Already installed (v${s.existingVersion || '?'})`
  if (s.status === 'update') return `Update available (v${s.existingVersion || '?'} → v${exportVersion.value || '?'})`
  return null
})

const overwriteCount = computed(() => toolOverwrites.value.filter((v, i) => v && toolItems.value[i]?.status !== 'new').length)
const newToolCount = computed(() => toolItems.value.filter(t => t.status === 'new').length)

const statusBadgeClass: Record<string, string> = {
  new: 'bg-green-900/30 border-green-700/40 text-green-300',
  update: 'bg-blue-900/30 border-blue-700/40 text-blue-300',
  exists: 'bg-gray-800 border-gray-700 text-gray-400',
}

// Vue Flow nodes/edges for pipeline preview
const flowNodes = computed<Node[]>(() => {
  if (!isPipeline.value || !props.data?.steps) return []
  return props.data.steps.map((step: any) => ({
    id: step.id,
    type: 'step',
    position: { x: step.pos_x ?? 0, y: step.pos_y ?? 0 },
    data: step,
  }))
})

const flowEdges = computed<Edge[]>(() => {
  if (!isPipeline.value || !props.data?.edges) return []
  return props.data.edges.map((e: any) => {
    const isMemoryEdge = (e.source_handle || '').endsWith('_memory')
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.source_handle,
      targetHandle: e.target_handle,
      type: 'pathfinding',
      animated: !isMemoryEdge,
      style: isMemoryEdge ? { stroke: '#38bdf8', strokeWidth: 2, strokeDasharray: '5 3' } : undefined,
    }
  })
})

function close() {
  emit('update:modelValue', false)
}

function confirm() {
  emit('confirm', overwriteResource.value, toolOverwrites.value)
  close()
}
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue && data" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" @click.self="close">
      <div class="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full p-5 space-y-4" :class="isPipeline ? 'max-w-3xl' : 'max-w-md'">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-gray-200">Import Review</h3>
          <button @click="close" class="text-gray-500 hover:text-gray-300 text-lg leading-none">&times;</button>
        </div>

        <!-- Resource status badge -->
        <div v-if="statusLabel" class="p-2 rounded text-xs font-medium" :class="status === 'exists' ? 'bg-yellow-900/20 border border-yellow-800/30 text-yellow-300' : 'bg-blue-900/20 border border-blue-800/30 text-blue-300'">
          <div class="flex items-center justify-between">
            <span>{{ statusLabel }}</span>
            <label v-if="status === 'exists'" class="flex items-center gap-1.5 cursor-pointer select-none">
              <input type="checkbox" v-model="overwriteResource" class="accent-yellow-500" />
              <span class="text-yellow-300/80">Overwrite</span>
            </label>
          </div>
        </div>

        <!-- Name & Description -->
        <div class="space-y-2">
          <div class="flex items-center gap-3">
            <img v-if="data?.image_url" :src="data.image_url" class="w-10 h-10 rounded-lg object-cover border border-gray-700 shrink-0 bg-black" />
            <LetterAvatar v-else :letter="exportName" :size="40" />
            <div>
              <span class="text-xs text-gray-500">Name</span>
              <p class="text-sm text-gray-200">{{ exportName }}</p>
            </div>
          </div>
          <div v-if="exportDescription">
            <span class="text-xs text-gray-500">Description</span>
            <p class="text-sm text-gray-400">{{ exportDescription }}</p>
          </div>
          <div class="flex gap-4">
            <div>
              <span class="text-xs text-gray-500">Type</span>
              <p class="text-sm text-gray-300 capitalize">{{ exportType }}</p>
            </div>
            <div v-if="exportVersion">
              <span class="text-xs text-gray-500">Version</span>
              <p class="text-sm text-gray-300">{{ exportVersion }}</p>
            </div>
            <div v-if="exportDate">
              <span class="text-xs text-gray-500">Exported</span>
              <p class="text-sm text-gray-300">{{ exportDate }}</p>
            </div>
          </div>
        </div>

        <!-- Pipeline Flow Chart Preview -->
        <div v-if="isPipeline && flowNodes.length">
          <span class="text-xs text-gray-500 uppercase font-medium">Pipeline Structure</span>
          <div class="mt-1 rounded-lg border border-gray-800 bg-gray-950" style="height: 300px">
            <VueFlow
              :key="flowKey"
              :nodes="flowNodes"
              :edges="flowEdges"
              :node-types="nodeTypes"
              :edge-types="edgeTypes"
              :nodes-draggable="false"
              :nodes-connectable="false"
              :elements-selectable="false"
              :pan-on-drag="true"
              :zoom-on-scroll="true"
              :min-zoom="0.1"
              :max-zoom="1.5"
              @pane-ready="onPaneReady"
            >
              <Background />
            </VueFlow>
          </div>
        </div>

        <!-- Pip Packages -->
        <div>
          <span class="text-xs text-gray-500 uppercase font-medium">Pip Packages</span>
          <div v-if="pipPackages.length" class="flex flex-wrap gap-1 mt-1">
            <span v-for="pkg in pipPackages" :key="pkg" class="inline-flex items-center px-2 py-0.5 bg-yellow-900/30 border border-yellow-700/40 rounded text-xs text-yellow-300">
              {{ pkg }}
            </span>
          </div>
          <p v-else class="text-xs text-gray-600 mt-1">No packages required</p>
        </div>

        <!-- Tools (pipeline only) -->
        <div v-if="isPipeline">
          <span class="text-xs text-gray-500 uppercase font-medium">Tools</span>
          <div v-if="toolItems.length" class="space-y-1 mt-1">
            <div v-for="(tool, idx) in toolItems" :key="idx" class="flex items-center gap-2 px-2 py-1.5 bg-gray-800 rounded text-xs">
              <!-- Overwrite checkbox for existing/update tools -->
              <input
                v-if="tool.status !== 'new'"
                type="checkbox"
                v-model="toolOverwrites[idx]"
                class="accent-blue-500 shrink-0"
              />
              <img v-if="tool.image_url" :src="tool.image_url" class="w-5 h-5 rounded object-cover shrink-0 bg-black" />
              <LetterAvatar v-else :letter="tool.name" :size="20" />
              <span class="text-gray-200">{{ tool.name }}</span>
              <span class="text-gray-500">{{ ToolTypeLabels[tool.type as ToolType] || 'Unknown' }}</span>
              <span class="ml-auto px-1.5 py-0.5 rounded border text-[10px] font-medium" :class="statusBadgeClass[tool.status]">
                {{ tool.status === 'new' ? 'New' : tool.status === 'update' ? `Update (v${tool.existingVersion || '?'})` : `Installed (v${tool.existingVersion || '?'})` }}
              </span>
            </div>
          </div>
          <p v-else class="text-xs text-gray-600 mt-1">No tools</p>
        </div>

        <!-- Warning / summary -->
        <div v-if="canImport && (pipPackages.length || newToolCount || overwriteCount)" class="p-2 bg-yellow-900/20 border border-yellow-800/30 rounded text-xs text-yellow-300">
          The following will happen on import:
          <ul class="list-disc list-inside mt-1 space-y-0.5 text-yellow-400/80">
            <li v-if="pipPackages.length">{{ pipPackages.length }} pip package(s) will be installed</li>
            <li v-if="newToolCount">{{ newToolCount }} tool(s) will be created</li>
            <li v-if="overwriteCount">{{ overwriteCount }} tool(s) will be overwritten</li>
          </ul>
        </div>

        <div class="flex justify-end gap-2 pt-1">
          <button @click="close" class="px-4 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-xs transition-colors">
            Cancel
          </button>
          <button
            @click="confirm"
            :disabled="!canImport"
            class="px-4 py-1.5 rounded-lg text-xs font-medium transition-colors"
            :class="canImport ? 'bg-blue-600 hover:bg-blue-700 text-white' : 'bg-gray-700 text-gray-500 cursor-not-allowed'"
          >
            {{ status === 'update' ? 'Update Existing' : status === 'exists' ? 'Overwrite & Import' : 'Confirm Import' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
