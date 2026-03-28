<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getTaskPlans, deleteTaskPlan } from '@/services/taskService'
import { createTaskPlan, type TaskPlan } from '@/models'
import { useToast } from '@/composables/useToast'
import { useAuth } from '@/composables/useAuth'
import LetterAvatar from '@/components/shared/LetterAvatar.vue'

const { show: toast } = useToast()
const auth = useAuth()
const router = useRouter()
const plans = ref<TaskPlan[]>([])
const search = ref('')
const loading = ref(true)
const displayList = computed(() => {
  const q = search.value.toLowerCase()
  return plans.value.filter(p =>
    p.name.toLowerCase().includes(q) || p.description.toLowerCase().includes(q) || (p.tag || '').toLowerCase().includes(q)
  )
})

async function load() {
  loading.value = true
  plans.value = await getTaskPlans()
  loading.value = false
}

function newTask() {
  router.push('/task/new')
}

function quickRun() {
  router.push('/task/new?quick=1')
}

async function remove(plan: TaskPlan) {
  if (confirm(`Delete "${plan.name || 'Untitled'}"?`)) {
    await deleteTaskPlan(plan.id)
    await load()
  }
}

onMounted(load)
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <div>
        <div class="flex items-center gap-2">
          <h1 class="text-2xl font-bold">Tasks</h1>
          <span class="px-1.5 py-0.5 text-[10px] font-semibold rounded bg-amber-900/40 text-amber-400 border border-amber-800/60 leading-none">BETA</span>
        </div>
        <p class="text-sm text-gray-500 mt-1">AI-planned task execution using your tools — this feature is in beta</p>
      </div>
      <div class="flex gap-2">
        <button @click="quickRun" class="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-sm font-medium transition-colors">
          Quick Run
        </button>
        <button @click="newTask" class="btn-primary">
          + New Task
        </button>
      </div>
    </div>

    <div class="flex items-center gap-4 mb-4">
      <input
        v-model="search"
        placeholder="Search tasks..."
        class="input-search"
      />
    </div>

    <div v-if="loading" class="text-gray-400">Loading...</div>
    <div v-else-if="displayList.length === 0" class="text-center py-16 space-y-4">
      <div class="text-gray-600">
        <svg class="w-12 h-12 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
        </svg>
      </div>
      <p class="text-gray-500">No saved tasks yet.</p>
      <p class="text-sm text-gray-600">Use <strong>Quick Run</strong> to execute a one-off task, or <strong>New Task</strong> to create a reusable plan.</p>
    </div>

    <div v-else class="border border-gray-800 rounded-lg overflow-hidden divide-y divide-gray-800/50">
      <div
        v-for="plan in displayList"
        :key="plan.id"
        class="flex items-center gap-3 px-4 py-3 hover:bg-gray-800/30 transition-colors"
      >
        <LetterAvatar :letter="plan.name || 'T'" :size="32" />
        <div class="flex-1 min-w-0">
          <div class="font-medium text-sm text-gray-50 truncate">{{ plan.name || 'Untitled Task' }}</div>
          <div class="text-xs text-gray-500 truncate">{{ plan.description || plan.request || 'No description' }}</div>
        </div>
        <span v-if="plan.tag" class="text-xs text-gray-600 shrink-0">{{ plan.tag }}</span>
        <span class="text-xs text-gray-600 shrink-0">{{ plan.plan?.length || 0 }} steps</span>
        <div class="flex gap-1 shrink-0">
          <router-link :to="`/task/${plan.id}`" class="px-2.5 py-1 bg-purple-600 text-white rounded text-xs hover:bg-purple-700 transition-colors">
            Run
          </router-link>
          <router-link :to="`/task/${plan.id}?edit=1`" class="btn-sm-outline">
            Edit
          </router-link>
          <button @click="remove(plan)" class="btn-sm-danger">
            Del
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
