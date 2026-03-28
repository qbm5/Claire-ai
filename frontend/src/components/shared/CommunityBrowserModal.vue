<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { browseCommunityItems, downloadCommunityItem, type CommunityItem } from '@/services/communityService'
import { useToast } from '@/composables/useToast'
import LetterAvatar from '@/components/shared/LetterAvatar.vue'

const props = defineProps<{
  modelValue: boolean
  resourceType: 'tool' | 'trigger' | 'pipeline'
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'import': [data: Record<string, any>]
}>()

const { show: toast } = useToast()

const items = ref<CommunityItem[]>([])
const loading = ref(false)
const downloading = ref<string | null>(null)
const search = ref('')
const sort = ref('newest')
const page = ref(1)
const totalPages = ref(1)
const total = ref(0)

const subtypeLabels: Record<string, Record<string, string>> = {
  tool: {
    LLM: 'LLM', Endpoint: 'Endpoint', Agent: 'Agent', Pipeline: 'Pipeline',
    If: 'If', Parallel: 'Parallel', End: 'End', Wait: 'Wait', Start: 'Start',
    LoopCounter: 'Loop', AskUser: 'Ask User', FileUpload: 'File Upload',
    FileDownload: 'File Download', Task: 'Task', Pause: 'Pause',
  },
  trigger: {
    Cron: 'Cron', FileWatcher: 'File Watcher', Webhook: 'Webhook', RSS: 'RSS', Custom: 'Custom',
  },
  pipeline: {
    Sequential: 'Sequential', Parallel: 'Parallel', Conditional: 'Conditional',
  },
}

const subtypeColor: Record<string, string> = {
  LLM: 'bg-purple-600/20 text-purple-400',
  Endpoint: 'bg-green-600/20 text-green-400',
  Agent: 'bg-orange-600/20 text-orange-400',
  Pipeline: 'bg-blue-600/20 text-blue-400',
  Cron: 'bg-blue-600/20 text-blue-400',
  FileWatcher: 'bg-green-600/20 text-green-400',
  Webhook: 'bg-purple-600/20 text-purple-400',
  RSS: 'bg-orange-600/20 text-orange-400',
  Custom: 'bg-cyan-600/20 text-cyan-400',
}

let searchDebounce: ReturnType<typeof setTimeout> | null = null

watch(() => props.modelValue, (open) => {
  if (open) {
    search.value = ''
    sort.value = 'newest'
    page.value = 1
    fetchItems()
  }
})

watch(search, () => {
  if (searchDebounce) clearTimeout(searchDebounce)
  searchDebounce = setTimeout(() => {
    page.value = 1
    fetchItems()
  }, 300)
})

watch(sort, () => {
  page.value = 1
  fetchItems()
})

async function fetchItems() {
  loading.value = true
  try {
    const result = await browseCommunityItems({
      type: props.resourceType,
      search: search.value || undefined,
      sort: sort.value,
      page: page.value,
      limit: 18,
    })
    items.value = result.items
    totalPages.value = result.pages
    total.value = result.total
  } catch (e: any) {
    toast(e.message || 'Failed to load community items', 'error')
    items.value = []
  } finally {
    loading.value = false
  }
}

async function importItem(item: CommunityItem) {
  downloading.value = item.id
  try {
    const result = await downloadCommunityItem(item.id)
    const data = result.config_json
    emit('import', data)
    close()
  } catch (e: any) {
    toast(e.message || 'Failed to download item', 'error')
  } finally {
    downloading.value = null
  }
}

function prevPage() {
  if (page.value > 1) { page.value--; fetchItems() }
}
function nextPage() {
  if (page.value < totalPages.value) { page.value++; fetchItems() }
}

function formatDate(iso: string): string {
  try { return new Date(iso).toLocaleDateString() } catch { return iso }
}

function onImgError(item: CommunityItem) {
  item.image_url = ''
}

function close() {
  emit('update:modelValue', false)
}

const typeLabel = computed(() => {
  const map: Record<string, string> = { tool: 'Tools', trigger: 'Triggers', pipeline: 'Pipelines' }
  return map[props.resourceType] || 'Items'
})
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" @click.self="close">
      <div class="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-4xl max-h-[85vh] flex flex-col">
        <!-- Header -->
        <div class="flex items-center justify-between px-5 py-4 border-b border-gray-800 shrink-0">
          <div>
            <h3 class="text-sm font-semibold text-gray-200">Community {{ typeLabel }}</h3>
            <p class="text-xs text-gray-500 mt-0.5">Browse and import shared {{ typeLabel.toLowerCase() }} from the community</p>
          </div>
          <button @click="close" class="text-gray-500 hover:text-gray-300 text-lg leading-none">&times;</button>
        </div>

        <!-- Search & Sort -->
        <div class="flex items-center gap-3 px-5 py-3 border-b border-gray-800/50 shrink-0">
          <div class="relative flex-1">
            <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd" />
            </svg>
            <input
              v-model="search"
              placeholder="Search..."
              class="w-full pl-9 pr-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-blue-500"
            />
          </div>
          <select
            v-model="sort"
            class="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-300 focus:outline-none focus:border-blue-500"
          >
            <option value="newest">Newest</option>
            <option value="popular">Most Popular</option>
            <option value="downloads">Most Downloads</option>
          </select>
        </div>

        <!-- Content -->
        <div class="flex-1 overflow-y-auto px-5 py-4">
          <div v-if="loading" class="flex items-center justify-center py-16">
            <svg class="animate-spin w-6 h-6 text-gray-500" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" class="opacity-25" />
              <path d="M4 12a8 8 0 018-8" stroke="currentColor" stroke-width="3" stroke-linecap="round" class="opacity-75" />
            </svg>
          </div>

          <div v-else-if="items.length === 0" class="text-gray-500 text-center py-16 text-sm">
            No {{ typeLabel.toLowerCase() }} found in the community.
          </div>

          <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            <div
              v-for="item in items"
              :key="item.id"
              class="bg-gray-800/50 border border-gray-800 rounded-xl p-4 hover:border-gray-600 transition-colors flex flex-col"
            >
              <!-- Header row -->
              <div class="flex items-center gap-2 mb-2">
                <img v-if="item.image_url" :src="item.image_url" @error="onImgError(item)" class="w-8 h-8 rounded object-cover shrink-0 bg-black" />
                <LetterAvatar v-else :letter="item.name" :size="32" />
                <h4 class="font-semibold text-gray-100 truncate min-w-0 text-sm">{{ item.name }}</h4>
                <span
                  v-if="item.item_subtype"
                  class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 ml-auto"
                  :class="subtypeColor[item.item_subtype] || 'bg-gray-700 text-gray-300'"
                >
                  {{ subtypeLabels[item.item_type]?.[item.item_subtype] || item.item_subtype }}
                </span>
              </div>

              <!-- Description -->
              <p class="text-xs text-gray-400 mb-3 line-clamp-2">{{ item.description || 'No description' }}</p>

              <!-- Tags -->
              <div v-if="item.tags?.length" class="flex flex-wrap gap-1 mb-3">
                <span v-for="tag in item.tags.slice(0, 3)" :key="tag" class="text-[10px] px-1.5 py-0.5 bg-gray-700/50 text-gray-400 rounded">{{ tag }}</span>
                <span v-if="item.tags.length > 3" class="text-[10px] text-gray-500">+{{ item.tags.length - 3 }}</span>
              </div>

              <!-- Meta row -->
              <div class="flex items-center gap-3 text-[10px] text-gray-500 mb-3 mt-auto">
                <span>{{ item.author_name }}</span>
                <span class="flex items-center gap-0.5">
                  <svg class="w-3 h-3" viewBox="0 0 20 20" fill="currentColor"><path d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" /></svg>
                  {{ item.download_count }}
                </span>
                <span v-if="item.upvote_count || item.downvote_count" class="flex items-center gap-1">
                  <span v-if="item.upvote_count" class="text-green-500">+{{ item.upvote_count }}</span>
                  <span v-if="item.downvote_count" class="text-red-400">-{{ item.downvote_count }}</span>
                </span>
                <span class="ml-auto">v{{ item.version }}</span>
              </div>

              <!-- Import button -->
              <button
                @click="importItem(item)"
                :disabled="downloading === item.id"
                class="w-full px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                :class="downloading === item.id
                  ? 'bg-gray-700 text-gray-500 cursor-wait'
                  : 'bg-blue-600/20 text-blue-400 hover:bg-blue-600/30'"
              >
                {{ downloading === item.id ? 'Downloading...' : 'Import' }}
              </button>
            </div>
          </div>
        </div>

        <!-- Pagination -->
        <div v-if="totalPages > 1" class="flex items-center justify-between px-5 py-3 border-t border-gray-800 shrink-0">
          <span class="text-xs text-gray-500">{{ total }} {{ typeLabel.toLowerCase() }} found</span>
          <div class="flex items-center gap-2">
            <button
              @click="prevPage"
              :disabled="page <= 1"
              class="px-3 py-1 rounded text-xs transition-colors"
              :class="page <= 1 ? 'text-gray-600 cursor-not-allowed' : 'text-gray-300 hover:bg-gray-800'"
            >Prev</button>
            <span class="text-xs text-gray-400">{{ page }} / {{ totalPages }}</span>
            <button
              @click="nextPage"
              :disabled="page >= totalPages"
              class="px-3 py-1 rounded text-xs transition-colors"
              :class="page >= totalPages ? 'text-gray-600 cursor-not-allowed' : 'text-gray-300 hover:bg-gray-800'"
            >Next</button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
