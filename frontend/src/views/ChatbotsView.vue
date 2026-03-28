<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getChatbots, deleteChatbot } from '@/services/chatbotService'
import { saveOrder } from '@/services/reorderService'
import { createChatBot, type ChatBot } from '@/models'
import { useAuth } from '@/composables/useAuth'
import TagFilterDropdown from '@/components/shared/TagFilterDropdown.vue'
import { NO_TAG, splitTags } from '@/utils/tags'
import draggable from 'vuedraggable'

const auth = useAuth()

const router = useRouter()
const chatbots = ref<ChatBot[]>([])
const search = ref('')
const loading = ref(true)
const showDisabled = ref(false)
const selectedTags = ref<string[]>([])
const displayList = ref<ChatBot[]>([])
const viewMode = ref<'grid' | 'list'>(localStorage.getItem('view_chatbots') as 'grid' | 'list' || 'list')
watch(viewMode, v => localStorage.setItem('view_chatbots', v))
const allTags = computed(() => {
  const tags = new Set<string>()
  let hasNoTag = false
  for (const b of chatbots.value) {
    const parts = splitTags(b.tag || '')
    if (parts.length) parts.forEach(p => tags.add(p))
    else hasNoTag = true
  }
  const sorted = [...tags].sort((a, b) => a.localeCompare(b))
  if (hasNoTag) sorted.unshift(NO_TAG)
  return sorted
})

watch([chatbots, search, showDisabled, selectedTags], () => {
  const q = search.value.toLowerCase()
  const tags = selectedTags.value
  displayList.value = chatbots.value.filter(b => {
    if (!showDisabled.value && !b.is_enabled) return false
    if (tags.length > 0) {
      const itemTags = splitTags(b.tag || '')
      if (!itemTags.length && !tags.includes(NO_TAG)) return false
      if (itemTags.length && !itemTags.some(it => tags.includes(it))) return false
    }
    return b.name.toLowerCase().includes(q) || b.tag.toLowerCase().includes(q) || b.description.toLowerCase().includes(q)
  })
}, { immediate: true })

async function onDragEnd() {
  const newVisibleIds = new Set(displayList.value.map(i => i.id))
  const hidden = chatbots.value.filter(i => !newVisibleIds.has(i.id))
  chatbots.value = [...displayList.value, ...hidden]
  await saveOrder('chatbots', chatbots.value.map(i => i.id))
}

async function load() {
  loading.value = true
  chatbots.value = await getChatbots()
  loading.value = false
}

function newBot() {
  const bot = createChatBot()
  router.push(`/chatbot/${bot.id}?new=1`)
}

async function remove(bot: ChatBot) {
  if (confirm(`Delete "${bot.name}"?`)) {
    await deleteChatbot(bot.id)
    await load()
  }
}

onMounted(load)
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold">Chatbots</h1>
      <button v-if="auth.canCreate('chatbots')" @click="newBot" class="btn-primary">
        + New Chatbot
      </button>
    </div>

    <div class="flex items-center gap-4 mb-4">
      <input
        v-model="search"
        placeholder="Search chatbots..."
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

    <div v-else-if="displayList.length === 0" class="text-gray-500 text-center py-12">
      No chatbots found. Create one to get started.
    </div>

    <!-- Grid view -->
    <draggable
      v-else-if="viewMode === 'grid'"
      v-model="displayList"
      item-key="id"
      class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
      ghost-class="opacity-30"
      @end="onDragEnd"
    >
      <template #item="{ element: bot }">
        <div
          class="card-hover flex flex-col cursor-grab active:cursor-grabbing"
        >
          <div class="flex items-start justify-between mb-2">
            <div class="flex items-center gap-2">
              <span v-if="!bot.is_enabled" class="w-1.5 h-1.5 rounded-full bg-gray-600 shrink-0" title="Disabled"></span>
              <h3 class="font-semibold text-gray-50" :class="{ 'text-gray-500': !bot.is_enabled }">{{ bot.name }}</h3>
            </div>
            <span v-if="bot.tag" class="text-xs px-2 py-0.5 bg-gray-800 rounded-full text-gray-400">{{ bot.tag }}</span>
          </div>
          <p class="text-sm text-gray-400 mb-4 line-clamp-2">{{ bot.description || 'No description' }}</p>
          <div class="text-xs text-gray-500 mb-3">
            <span class="capitalize">{{ bot.source_type }}</span>
            <span v-if="bot.model" class="ml-2">{{ bot.model }}</span>
          </div>
          <div class="flex gap-2 mt-auto">
            <router-link :to="`/chat/${bot.id}`" class="btn-sm-ghost">
              Chat
            </router-link>
            <router-link v-if="auth.canEdit('chatbots')" :to="`/chatbot/${bot.id}`" class="px-3 py-1.5 bg-gray-800 text-gray-300 rounded-lg text-xs hover:bg-gray-700 transition-colors">
              Edit
            </router-link>
            <button v-if="auth.canDelete('chatbots')" @click="remove(bot)" class="btn-sm-danger-ghost ml-auto">
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
      <template #item="{ element: bot }">
        <div class="flex items-center gap-3 px-3 py-2.5 hover:bg-gray-800/30 transition-colors cursor-grab active:cursor-grabbing group">
          <svg class="w-3.5 h-3.5 text-gray-700 shrink-0" viewBox="0 0 16 16" fill="currentColor"><circle cx="5" cy="3" r="1.5"/><circle cx="11" cy="3" r="1.5"/><circle cx="5" cy="8" r="1.5"/><circle cx="11" cy="8" r="1.5"/><circle cx="5" cy="13" r="1.5"/><circle cx="11" cy="13" r="1.5"/></svg>
          <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="bot.is_enabled ? 'bg-green-400' : 'bg-gray-600'"></span>
          <span class="font-medium text-sm truncate min-w-[120px] max-w-[200px]" :class="bot.is_enabled ? 'text-gray-50' : 'text-gray-500'">{{ bot.name }}</span>
          <span class="text-sm text-gray-500 truncate flex-1 hidden sm:inline">{{ bot.description || 'No description' }}</span>
          <span v-if="bot.tag" class="text-xs px-2 py-0.5 bg-gray-800 rounded-full text-gray-400 shrink-0 hidden md:inline">{{ bot.tag }}</span>
          <span class="text-xs text-gray-600 shrink-0 hidden lg:inline">{{ bot.model || '' }}</span>
          <div class="flex gap-1 shrink-0 ml-auto">
            <router-link :to="`/chat/${bot.id}`" class="btn-sm-outline">Chat</router-link>
            <router-link v-if="auth.canEdit('chatbots')" :to="`/chatbot/${bot.id}`" class="px-2 py-1 text-gray-400 rounded text-xs hover:bg-gray-700 transition-colors">Edit</router-link>
            <button v-if="auth.canDelete('chatbots')" @click="remove(bot)" class="btn-sm-danger">Del</button>
          </div>
        </div>
      </template>
    </draggable>
  </div>
</template>
