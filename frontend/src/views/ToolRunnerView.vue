<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getTool, runTool } from '@/services/toolService'
import type { AiTool } from '@/models'
import { ToolTypeLabels, type ToolType } from '@/models'
import DynamicInput from '@/components/shared/DynamicInput.vue'

const props = defineProps<{ id: string }>()
const router = useRouter()

const tool = ref<AiTool | null>(null)
const loading = ref(true)
const running = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    tool.value = await getTool(props.id)
  } catch (e: any) {
    error.value = e.message || 'Failed to load tool'
  } finally {
    loading.value = false
  }
})

async function run() {
  if (!tool.value) return
  running.value = true
  error.value = ''
  try {
    const inputs = tool.value.request_inputs.map(inp => ({
      name: inp.name,
      value: inp.value,
      type: inp.type,
    }))
    const result = await runTool(tool.value.id, inputs)
    router.push(`/pipeline-run/${result.id}`)
  } catch (e: any) {
    error.value = e.message || 'Failed to run tool'
    running.value = false
  }
}
</script>

<template>
  <div class="p-6 max-w-2xl mx-auto">
    <router-link to="/tools" class="text-sm text-gray-400 hover:text-gray-50 transition-colors mb-6 inline-flex items-center gap-1">
      &larr; Back to Tools
    </router-link>

    <div v-if="loading" class="text-gray-400 mt-8">Loading tool...</div>
    <div v-else-if="error && !tool" class="text-red-400 mt-8">{{ error }}</div>

    <template v-else-if="tool">
      <h1 class="text-2xl font-bold mt-4 mb-1">{{ tool.name }}</h1>
      <div class="flex items-center gap-2 mb-1">
        <span class="text-xs px-2 py-0.5 rounded-full font-medium bg-gray-800 text-gray-400">
          {{ ToolTypeLabels[tool.type as ToolType] || 'Unknown' }}
        </span>
        <span v-if="tool.tag" class="text-xs text-gray-500">{{ tool.tag }}</span>
      </div>
      <p v-if="tool.description" class="text-gray-400 text-sm mb-6">{{ tool.description }}</p>
      <div v-else class="mb-6"></div>

      <div class="space-y-4">
        <div v-for="(input, idx) in tool.request_inputs" :key="idx" class="flex flex-col gap-1.5">
          <label class="text-sm font-medium text-gray-300">
            {{ input.name }}
            <span v-if="input.is_required" class="text-red-400">*</span>
          </label>
          <p v-if="input.description" class="text-xs text-gray-500">{{ input.description }}</p>

          <DynamicInput
            v-model="input.value"
            :type="input.type"
            :data="input.data"
            :placeholder="input.name"
            :label="input.name"
          />
        </div>
      </div>

      <div v-if="error" class="mt-4 text-sm text-red-400">{{ error }}</div>

      <button
        @click="run"
        :disabled="running"
        class="mt-6 px-6 py-2.5 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition-colors"
      >
        {{ running ? 'Starting...' : 'Run Tool' }}
      </button>
    </template>
  </div>
</template>
