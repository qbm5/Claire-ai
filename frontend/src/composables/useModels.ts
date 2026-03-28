import { ref, computed } from 'vue'
import { getSettings } from '@/services/settingsService'

interface ModelEntry {
  id: string
  name: string
  provider: 'anthropic' | 'openai' | 'google' | 'xai' | 'local'
  input_cost: number
  output_cost: number
}

const allModels = ref<ModelEntry[]>([])
const hasAnthropicKey = ref(false)
const hasOpenaiKey = ref(false)
const hasGoogleKey = ref(false)
const hasXaiKey = ref(false)
const hasLocalUrl = ref(false)
let loaded = false

export async function loadModels() {
  if (loaded) return
  const data = await getSettings()
  allModels.value = (data.models || []) as ModelEntry[]
  hasAnthropicKey.value = !!data.ANTHROPIC_API_KEY
  hasOpenaiKey.value = !!data.OPENAI_API_KEY
  hasGoogleKey.value = !!data.GOOGLE_API_KEY
  hasXaiKey.value = !!data.XAI_API_KEY
  hasLocalUrl.value = !!data.LOCAL_LLM_URL
  loaded = true
}

export function invalidateModels() {
  loaded = false
}

const models = computed(() =>
  allModels.value.filter(m => {
    if (m.provider === 'openai') return hasOpenaiKey.value
    if (m.provider === 'anthropic') return hasAnthropicKey.value
    if (m.provider === 'google') return hasGoogleKey.value
    if (m.provider === 'xai') return hasXaiKey.value
    if (m.provider === 'local') return hasLocalUrl.value
    return true
  })
)

export function useModels() {
  return { models, allModels, hasAnthropicKey, hasOpenaiKey, hasGoogleKey, hasXaiKey, hasLocalUrl, loadModels, invalidateModels }
}
