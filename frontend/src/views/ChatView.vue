<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { getChatbot, wsChat, getChatHistories, saveChatHistory, deleteChatHistory } from '@/services/chatbotService'
import { getUid, type ChatBot, type ChatMessage, type ChatHistory } from '@/models'
import { useTheme } from '@/composables/useTheme'
import { renderMarkdown } from '@/composables/useArtifactRenderer'

const { theme } = useTheme()

const props = defineProps<{ id: string }>()
const router = useRouter()

const bot = ref<ChatBot | null>(null)
const messages = ref<ChatMessage[]>([])
const input = ref('')
const loading = ref(false)
const streaming = ref(false)
const sources = ref<string[]>([])
const historyId = ref(getUid())
const histories = ref<ChatHistory[]>([])
const chatContainer = ref<HTMLElement | null>(null)

onMounted(async () => {
  const data = await getChatbot(props.id)
  if (data && !('error' in data)) {
    bot.value = data as ChatBot
  }
  histories.value = await getChatHistories(props.id)
})

function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

async function send() {
  const query = input.value.trim()
  if (!query || streaming.value) return

  input.value = ''
  messages.value.push({ id: getUid(), role: 'user', content: query, sources: [], timestamp: new Date().toISOString() })
  scrollToBottom()

  const assistantMsg: ChatMessage = { id: getUid(), role: 'assistant', content: '', sources: [], timestamp: new Date().toISOString() }
  messages.value.push(assistantMsg)
  streaming.value = true
  sources.value = []

  try {
    await wsChat(props.id, query, historyId.value, (data) => {
      if (data.type === 'text') {
        assistantMsg.content += data.text
        scrollToBottom()
      } else if (data.type === 'sources') {
        assistantMsg.sources = data.sources
        sources.value = data.sources
      } else if (data.type === 'error') {
        assistantMsg.content += `\n\nError: ${data.text}`
      }
    })
  } catch (e) {
    assistantMsg.content += '\n\nConnection error'
  }
  streaming.value = false

  // Auto-save history
  await saveChatHistory(props.id, {
    id: historyId.value,
    chatbot_id: props.id,
    user_id: 'default',
    title: query.substring(0, 50),
    messages: messages.value,
  })
}

function loadHistory(h: ChatHistory) {
  historyId.value = h.id
  messages.value = h.messages || []
  scrollToBottom()
}

function newChat() {
  historyId.value = getUid()
  messages.value = []
  sources.value = []
}

function renderMd(text: string): string {
  return renderMarkdown(text)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <div class="flex h-full">
    <!-- History sidebar -->
    <div class="w-64 bg-gray-900 border-r border-gray-800 flex flex-col">
      <div class="p-3 border-b border-gray-800 flex items-center justify-between">
        <button @click="router.push('/chatbots')" class="text-gray-400 hover:text-gray-50 text-sm">&larr; Back</button>
        <button @click="newChat" class="text-xs px-3 py-1 bg-blue-600/20 text-blue-400 rounded-lg hover:bg-blue-600/30">New Chat</button>
      </div>
      <div class="flex-1 overflow-auto p-2 space-y-1">
        <div
          v-for="h in histories"
          :key="h.id"
          @click="loadHistory(h)"
          class="px-3 py-2 text-sm rounded-lg cursor-pointer truncate"
          :class="h.id === historyId ? 'bg-gray-800 text-gray-50' : 'text-gray-400 hover:bg-gray-800/50'"
        >
          {{ h.title || 'Untitled' }}
        </div>
      </div>
    </div>

    <!-- Chat area -->
    <div class="flex-1 flex flex-col">
      <div class="p-4 border-b border-gray-800">
        <h2 class="font-semibold">{{ bot?.name || 'Chat' }}</h2>
        <p class="text-xs text-gray-500">{{ bot?.description }}</p>
      </div>

      <div ref="chatContainer" class="flex-1 overflow-auto p-4 space-y-4">
        <div v-if="messages.length === 0" class="text-center text-gray-500 py-20">
          Start a conversation
        </div>
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="flex"
          :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <div
            class="max-w-[80%] rounded-xl px-4 py-3 text-sm"
            :class="msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-200'"
          >
            <div v-if="msg.role === 'assistant'" v-html="renderMd(msg.content)" class="prose prose-sm max-w-none" :class="{ 'prose-invert': theme === 'dark' }"></div>
            <div v-else>{{ msg.content }}</div>
            <div v-if="msg.sources?.length" class="mt-2 pt-2 border-t border-gray-700">
              <div class="text-xs text-gray-400">Sources:</div>
              <div v-for="s in msg.sources" :key="s" class="text-xs text-blue-400 truncate">{{ s }}</div>
            </div>
          </div>
        </div>
        <div v-if="streaming" class="flex justify-start">
          <div class="text-gray-500 text-sm animate-pulse">Thinking...</div>
        </div>
      </div>

      <div class="p-4 border-t border-gray-800">
        <div class="flex gap-2">
          <textarea
            v-model="input"
            @keydown="onKeydown"
            placeholder="Type a message..."
            rows="2"
            class="flex-1 px-4 py-2 bg-gray-800 border border-gray-700 rounded-xl text-sm resize-none focus:outline-none focus:border-blue-500"
          ></textarea>
          <button @click="send" :disabled="streaming" class="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded-xl text-sm font-medium transition-colors self-end">
            Send
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
