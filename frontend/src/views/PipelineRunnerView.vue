<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getPipeline, runPipeline } from '@/services/pipelineService'
import { createPipelineRun, type AiPipeline } from '@/models'
import DynamicInput from '@/components/shared/DynamicInput.vue'

const props = defineProps<{ id: string }>()
const router = useRouter()

const pipeline = ref<AiPipeline | null>(null)
const loading = ref(true)
const running = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    pipeline.value = await getPipeline(props.id)
  } catch (e: any) {
    error.value = e.message || 'Failed to load pipeline'
  } finally {
    loading.value = false
  }
})

async function run() {
  if (!pipeline.value) return
  running.value = true
  error.value = ''
  try {
    const plRun = createPipelineRun(pipeline.value)
    const result = await runPipeline(plRun)
    router.push(`/pipeline-run/${result.id}`)
  } catch (e: any) {
    error.value = e.message || 'Failed to start pipeline'
    running.value = false
  }
}
</script>

<template>
  <div class="p-6 max-w-2xl mx-auto">
    <router-link to="/pipelines" class="text-sm text-gray-400 hover:text-gray-50 transition-colors mb-6 inline-flex items-center gap-1">
      &larr; Back to Pipelines
    </router-link>

    <div v-if="loading" class="text-gray-400 mt-8">Loading pipeline...</div>
    <div v-else-if="error && !pipeline" class="text-red-400 mt-8">{{ error }}</div>

    <template v-else-if="pipeline">
      <h1 class="text-2xl font-bold mt-4 mb-1">{{ pipeline.name }}</h1>
      <p v-if="pipeline.description" class="text-gray-400 text-sm mb-6">{{ pipeline.description }}</p>
      <div v-else class="mb-6"></div>

      <div class="space-y-4">
        <div v-for="(input, idx) in pipeline.inputs" :key="idx" class="flex flex-col gap-1.5">
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
        {{ running ? 'Starting...' : 'Run Pipeline' }}
      </button>
    </template>
  </div>
</template>
