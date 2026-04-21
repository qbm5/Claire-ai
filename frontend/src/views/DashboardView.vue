<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getDashboard, killProcess, forceStopRun, type DashboardData } from '@/services/dashboardService'
import { onEvent } from '@/services/eventBus'
import { useAuth } from '@/composables/useAuth'
import { get } from '@/services/api'
import DashboardCharts from '@/components/dashboard/DashboardCharts.vue'
import UserSelectDropdown, { type UserOption } from '@/components/shared/UserSelectDropdown.vue'

const router = useRouter()
const { isAdmin, authRequired } = useAuth()

const userFilter = ref(localStorage.getItem('dashboard_userFilter') || '')
const userList = ref<UserOption[]>([])
const data = ref<DashboardData | null>(null)
const loading = ref(true)

const viewMode = ref<'table' | 'charts'>((localStorage.getItem('dashboard_viewMode') as 'table' | 'charts') || 'table')
watch(viewMode, (v) => localStorage.setItem('dashboard_viewMode', v))

const sinceFilter = ref(localStorage.getItem('dashboard_since') || '')

watch([userFilter, sinceFilter], ([u, s]) => {
  localStorage.setItem('dashboard_userFilter', u)
  localStorage.setItem('dashboard_since', s)
  load()
})

const sinceOptions = [
  { value: '', label: 'Latest 20' },
  { value: '1h', label: 'Past Hour' },
  { value: 'today', label: 'Today' },
  { value: '24h', label: 'Past 24h' },
  { value: '7d', label: 'This Week' },
  { value: '30d', label: 'This Month' },
  { value: '365d', label: 'This Year' },
  { value: 'all', label: 'All Time' },
]

let refreshTimer: ReturnType<typeof setInterval> | null = null
let unsub: (() => void) | null = null

async function load() {
  try {
    data.value = await getDashboard(sinceFilter.value || undefined, userFilter.value || undefined)
  } catch (e) {
    console.error('Dashboard fetch failed:', e)
  } finally {
    loading.value = false
  }
}

async function handleKillProcess(pid: number) {
  if (!confirm(`Kill process ${pid}?`)) return
  await killProcess(pid)
  await load()
}

async function handleStopRun(runId: string) {
  await forceStopRun(runId)
  await load()
}

function navigateToRun(run: { id: string; run_type?: string }) {
  router.push(`/pipeline-run/${run.id}`)
}

function runTypeLabel(run: { pipeline_id: string; tool_id?: string; run_type?: string }): string {
  if (isToolRun(run)) return 'Tool'
  return 'Pipeline'
}

function runTypeBadgeClass(run: { pipeline_id: string; tool_id?: string; run_type?: string }): string {
  if (isToolRun(run)) return 'bg-purple-900/50 text-purple-400'
  return 'bg-blue-900/50 text-blue-400'
}

const TOOL_RUNS_ID = '__tool_runs__'

const statusLabel: Record<number, string> = {
  0: 'Pending', 1: 'Running', 2: 'Completed', 3: 'Failed', 4: 'Paused', 5: 'Waiting',
}
const statusBadge: Record<number, string> = {
  0: 'bg-gray-700 text-gray-300',
  1: 'bg-blue-900/60 text-blue-400',
  2: 'bg-green-900/60 text-green-400',
  3: 'bg-red-900/60 text-red-400',
  4: 'bg-yellow-900/60 text-yellow-400',
  5: 'bg-indigo-900/60 text-indigo-400',
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '-'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

function formatCost(cost: number): string {
  if (!cost) return '-'
  return `$${cost.toFixed(4)}`
}

function timeAgo(iso: string): string {
  if (!iso) return '-'
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function isToolRun(run: { pipeline_id: string; tool_id?: string }): boolean {
  return run.pipeline_id === TOOL_RUNS_ID || !!run.tool_id
}

const stats = computed(() => data.value?.stats)

const totalCost = computed(() => {
  if (!data.value?.recent_runs.length) return 0
  return data.value.recent_runs.reduce((sum, r) => sum + (r.cost || 0), 0)
})

let unsubProc: (() => void) | null = null

onMounted(async () => {
  load()
  refreshTimer = setInterval(load, 15000)
  unsub = onEvent('run_log', () => load())
  unsubProc = onEvent('process_change', () => load())
  // Fetch user list for admin filter dropdown
  if (authRequired.value && isAdmin.value) {
    try {
      const users = await get<UserOption[]>('/auth/users')
      userList.value = users
    } catch { /* ignore — dropdown just won't show */ }
  }
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (unsub) unsub()
  if (unsubProc) unsubProc()
})
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto space-y-6">
    <!-- Header -->
    <h1 class="text-2xl font-bold">Dashboard</h1>

    <div v-if="loading" class="text-gray-400">Loading...</div>

    <template v-else-if="data">
      <!-- Stat Cards -->
      <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <!-- Pipelines -->
        <router-link to="/pipelines" class="card-hover group">
          <div class="flex items-center justify-between mb-2">
            <span class="text-sm text-gray-400 group-hover:text-gray-300">Pipelines</span>
            <svg class="w-5 h-5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
          </div>
          <div class="text-2xl font-bold">{{ stats?.pipelines ?? 0 }}</div>
        </router-link>

        <!-- Tools -->
        <router-link to="/tools" class="card-hover group">
          <div class="flex items-center justify-between mb-2">
            <span class="text-sm text-gray-400 group-hover:text-gray-300">Tools</span>
            <svg class="w-5 h-5 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066zM15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
          </div>
          <div class="text-2xl font-bold">{{ stats?.tools ?? 0 }}</div>
        </router-link>

        <!-- Triggers -->
        <router-link to="/triggers" class="card-hover group">
          <div class="flex items-center justify-between mb-2">
            <span class="text-sm text-gray-400 group-hover:text-gray-300">Triggers</span>
            <svg class="w-5 h-5 text-yellow-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" /></svg>
          </div>
          <div class="text-2xl font-bold">{{ stats?.triggers ?? 0 }}</div>
        </router-link>

        <!-- Active Runs -->
        <div class="card-base">
          <div class="flex items-center justify-between mb-2">
            <span class="text-sm text-gray-400">Active Runs</span>
            <svg class="w-5 h-5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path d="M5.636 18.364a9 9 0 010-12.728m12.728 0a9 9 0 010 12.728M12 12v.01" /><path d="M8.464 15.536a5 5 0 010-7.072m7.072 0a5 5 0 010 7.072" /></svg>
          </div>
          <div class="text-2xl font-bold flex items-center gap-2">
            {{ stats?.active_runs ?? 0 }}
            <span v-if="(stats?.active_runs ?? 0) > 0" class="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
          </div>
        </div>

        <!-- Active Processes -->
        <div class="card-base">
          <div class="flex items-center justify-between mb-2">
            <span class="text-sm text-gray-400">Active Processes</span>
            <svg class="w-5 h-5 text-orange-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
          </div>
          <div class="text-2xl font-bold flex items-center gap-2">
            {{ stats?.active_processes ?? 0 }}
            <span v-if="(stats?.active_processes ?? 0) > 0" class="w-2 h-2 rounded-full bg-orange-500 animate-pulse"></span>
          </div>
        </div>

      </div>

      <!-- Active Runs + Processes + Triggers Row -->
      <div class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-4 gap-4">
        <!-- Active Runs Widget -->
        <div class="card-base">
          <div class="flex items-center gap-2 mb-3">
            <h2 class="text-sm font-semibold text-gray-300">Active Runs</h2>
            <span v-if="data.active_runs.length" class="text-xs px-1.5 py-0.5 bg-blue-900/60 text-blue-400 rounded-full">{{ data.active_runs.length }}</span>
          </div>
          <div v-if="data.active_runs.length === 0" class="text-sm text-gray-600 py-6 text-center">No active runs</div>
          <div v-else class="space-y-2">
            <div
              v-for="run in data.active_runs"
              :key="run.id"
              class="flex items-center gap-3 px-3 py-2 rounded-lg bg-gray-800/50 hover:bg-gray-800 transition-colors cursor-pointer"
              @click="navigateToRun(run)"
            >
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span
                    class="text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded shrink-0"
                    :class="isToolRun(run) ? 'bg-purple-900/50 text-purple-400' : 'bg-blue-900/50 text-blue-400'"
                  >{{ isToolRun(run) ? 'Tool' : 'Pipeline' }}</span>
                  <span class="text-sm font-medium text-gray-50 truncate">{{ run.pipeline_name }}</span>
                </div>
                <div class="flex items-center gap-2 mt-0.5">
                  <span class="text-xs px-1.5 py-0.5 rounded" :class="statusBadge[run.status] || statusBadge[0]">{{ statusLabel[run.status] || 'Unknown' }}</span>
                  <span class="text-xs text-gray-500">Step {{ run.current_step }}/{{ run.total_steps }}</span>
                  <span class="text-xs text-gray-600">{{ timeAgo(run.created_at) }}</span>
                  <span v-if="run.cost" class="text-xs text-gray-500">{{ formatCost(run.cost) }}</span>
                </div>
              </div>
              <button
                @click.stop="handleStopRun(run.id)"
                class="px-2 py-1 text-xs bg-red-900/40 text-red-400 rounded hover:bg-red-900/70 transition-colors shrink-0"
              >Stop</button>
            </div>
          </div>
        </div>

        <!-- Active Processes Widget -->
        <div class="card-base">
          <div class="flex items-center gap-2 mb-3">
            <h2 class="text-sm font-semibold text-gray-300">Active Processes</h2>
            <span v-if="data.processes.length" class="text-xs px-1.5 py-0.5 bg-orange-900/60 text-orange-400 rounded-full">{{ data.processes.length }}</span>
            <span v-if="data.job_object_active" class="ml-auto flex items-center gap-1 text-xs text-gray-500">
              <span class="w-1.5 h-1.5 rounded-full bg-green-500"></span>
              Job Object
            </span>
          </div>
          <div v-if="data.processes.length === 0" class="text-sm text-gray-600 py-6 text-center">No active subprocesses</div>
          <div v-else class="space-y-2">
            <div
              v-for="proc in data.processes"
              :key="proc.pid"
              class="flex items-center gap-3 px-3 py-2 rounded-lg bg-gray-800/50"
            >
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-xs text-gray-500 font-mono">PID {{ proc.pid }}</span>
                  <span v-if="proc.running" class="w-1.5 h-1.5 rounded-full bg-green-500"></span>
                  <span v-else class="w-1.5 h-1.5 rounded-full bg-gray-600"></span>
                </div>
                <div class="text-sm text-gray-400 truncate mt-0.5 font-mono">{{ proc.command.slice(0, 60) }}</div>
              </div>
              <button
                @click="handleKillProcess(proc.pid)"
                class="px-2 py-1 text-xs bg-red-900/40 text-red-400 rounded hover:bg-red-900/70 transition-colors shrink-0"
              >Kill</button>
            </div>
          </div>
        </div>

        <!-- Active Triggers Widget -->
        <div class="card-base">
          <div class="flex items-center gap-2 mb-3">
            <h2 class="text-sm font-semibold text-gray-300">Active Triggers</h2>
            <span v-if="data.active_triggers?.length" class="text-xs px-1.5 py-0.5 bg-yellow-900/60 text-yellow-400 rounded-full">{{ data.active_triggers.length }}</span>
          </div>
          <div v-if="!data.active_triggers?.length" class="text-sm text-gray-600 py-6 text-center">No active triggers</div>
          <div v-else class="space-y-2">
            <router-link
              v-for="trig in data.active_triggers"
              :key="trig.id"
              :to="`/trigger/${trig.id}`"
              class="flex items-center gap-3 px-3 py-2 rounded-lg bg-gray-800/50 hover:bg-gray-800 transition-colors block"
            >
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded shrink-0 bg-yellow-900/50 text-yellow-400">{{ trig.trigger_type_label }}</span>
                  <span class="text-sm font-medium text-gray-50 truncate">{{ trig.name }}</span>
                </div>
                <div class="flex items-center gap-2 mt-0.5">
                  <span v-if="trig.last_status" class="text-xs px-1.5 py-0.5 rounded" :class="trig.last_status === 'OK' ? 'bg-green-900/60 text-green-400' : 'bg-red-900/60 text-red-400'">{{ trig.last_status }}</span>
                  <span v-if="trig.fire_count" class="text-xs text-gray-500">{{ trig.fire_count }} fires</span>
                  <span v-if="trig.last_fired_at" class="text-xs text-gray-600">{{ timeAgo(trig.last_fired_at) }}</span>
                  <span v-if="trig.connections_count" class="text-xs text-gray-600">{{ trig.connections_count }} conn.</span>
                </div>
              </div>
            </router-link>
          </div>
        </div>
      </div>

      <!-- Recent Runs — fixed height with internal scroll -->
      <div class="bg-gray-900 border border-gray-800 rounded-xl flex flex-col" style="height: 480px;">
        <!-- Sticky header -->
        <div class="flex items-center justify-between px-4 py-3 border-b border-gray-800 shrink-0">
          <div class="flex items-center gap-2">
            <h2 class="text-sm font-semibold text-gray-300">Runs</h2>
            <span v-if="data.recent_runs.length" class="text-xs text-gray-500">({{ data.recent_runs.length }})</span>
            <span v-if="totalCost > 0" class="text-xs px-2 py-0.5 bg-emerald-900/40 text-emerald-400 rounded-full font-medium">${{ totalCost.toFixed(4) }}</span>
            <!-- Admin user filter (only when auth is enabled) -->
            <UserSelectDropdown
              v-if="authRequired && isAdmin && userList.length > 0"
              :model-value="userFilter"
              @update:model-value="userFilter = $event"
              :users="userList"
            />
            <!-- Table / Charts toggle -->
            <div class="flex items-center bg-gray-800 rounded-lg p-0.5 ml-2">
              <button
                @click="viewMode = 'table'"
                class="p-1 rounded transition-colors"
                :class="viewMode === 'table' ? 'bg-gray-700 text-gray-100' : 'text-gray-500 hover:text-gray-300'"
                title="Table view"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path d="M3 10h18M3 14h18M3 6h18M3 18h18" /></svg>
              </button>
              <button
                @click="viewMode = 'charts'"
                class="p-1 rounded transition-colors"
                :class="viewMode === 'charts' ? 'bg-gray-700 text-gray-100' : 'text-gray-500 hover:text-gray-300'"
                title="Charts view"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path d="M3 3v18h18M7 16l4-4 4 4 5-6" /></svg>
              </button>
            </div>
          </div>
          <div class="flex gap-1">
            <button
              v-for="opt in sinceOptions"
              :key="opt.value"
              @click="sinceFilter = opt.value"
              class="px-2.5 py-1 text-xs rounded-lg transition-colors"
              :class="sinceFilter === opt.value
                ? 'bg-gray-700 text-gray-100'
                : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800'"
            >{{ opt.label }}</button>
          </div>
        </div>

        <!-- Scrollable table body -->
        <div v-if="viewMode === 'table'" class="flex-1 overflow-y-auto min-h-0">
          <div v-if="data.recent_runs.length === 0" class="text-sm text-gray-600 py-12 text-center">No runs found</div>
          <table v-else class="w-full text-sm">
            <thead class="sticky top-0 bg-gray-900 z-10">
              <tr class="text-left text-xs text-gray-500 border-b border-gray-800">
                <th class="px-4 py-2 font-medium">Type</th>
                <th class="py-2 pr-4 font-medium">Name</th>
                <th class="py-2 pr-4 font-medium">Status</th>
                <th class="py-2 pr-4 font-medium">Started</th>
                <th class="py-2 pr-4 font-medium">Duration</th>
                <th class="py-2 pr-4 font-medium text-right">Cost</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-800/50">
              <tr
                v-for="run in data.recent_runs"
                :key="run.id"
                class="hover:bg-gray-800/30 transition-colors cursor-pointer"
                @click="navigateToRun(run)"
              >
                <td class="px-4 py-2">
                  <span
                    class="text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded"
                    :class="runTypeBadgeClass(run)"
                  >{{ runTypeLabel(run) }}</span>
                </td>
                <td class="py-2 pr-4 text-gray-50 truncate max-w-[200px]">{{ run.pipeline_name }}</td>
                <td class="py-2 pr-4">
                  <span class="text-xs px-1.5 py-0.5 rounded" :class="statusBadge[run.status] || statusBadge[0]">{{ statusLabel[run.status] || 'Unknown' }}</span>
                </td>
                <td class="py-2 pr-4 text-gray-500">{{ timeAgo(run.created_at) }}</td>
                <td class="py-2 pr-4 text-gray-500">{{ formatDuration(run.duration_s) }}</td>
                <td class="py-2 pr-4 text-right text-gray-500">{{ formatCost(run.cost) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Charts view -->
        <div v-else class="flex-1 overflow-y-auto min-h-0">
          <DashboardCharts :runs="data.recent_runs" :since-filter="sinceFilter" />
        </div>
      </div>
    </template>
  </div>
</template>
