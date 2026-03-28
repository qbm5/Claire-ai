import type { ChatBot, ChatHistory } from '@/models'
import { get, post, del, wsConnect, API_BASE } from './api'

export function getChatbots(): Promise<ChatBot[]> {
  return get<ChatBot[]>('/chatbots')
}

export function getChatbot(id: string): Promise<ChatBot> {
  return get<ChatBot>(`/chatbots/${id}`)
}

export function saveChatbot(chatbot: ChatBot): Promise<{ response: string }> {
  return post<{ response: string }>('/chatbots', chatbot)
}

export function deleteChatbot(id: string): Promise<void> {
  return del<void>(`/chatbots/${id}`)
}

export function reindexChatbot(id: string): Promise<{ response: string; count: number }> {
  return post<{ response: string; count: number }>(`/chatbots/${id}/index`, {})
}

export function getChatHistories(chatbotId: string): Promise<ChatHistory[]> {
  return get<ChatHistory[]>(`/chatbots/${chatbotId}/histories`)
}

export function saveChatHistory(chatbotId: string, history: ChatHistory): Promise<{ response: string }> {
  return post<{ response: string }>(`/chatbots/${chatbotId}/histories`, history)
}

export function deleteChatHistory(id: string): Promise<void> {
  return del<void>(`/chatbots/histories/${id}`)
}

export function getUploads(chatbotId: string): Promise<{ name: string; size: number }[]> {
  return get<{ name: string; size: number }[]>(`/uploads/${chatbotId}`)
}

export async function uploadFiles(chatbotId: string, files: File[]): Promise<{ response: string; files: string[] }> {
  const formData = new FormData()
  for (const file of files) {
    formData.append('files', file)
  }
  const res = await fetch(`${API_BASE}/upload/${chatbotId}`, {
    method: 'POST',
    body: formData,
  })
  return res.json()
}

export function deleteUpload(chatbotId: string, filename: string): Promise<void> {
  return del<void>(`/uploads/${chatbotId}/${encodeURIComponent(filename)}`)
}

export function wsChat(
  chatbotId: string,
  query: string,
  historyId: string,
  onMessage: (data: any) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const ws = wsConnect('/chat')
    ws.onopen = () => ws.send(JSON.stringify({ chatbot_id: chatbotId, query, history_id: historyId }))
    ws.onmessage = (e) => onMessage(JSON.parse(e.data))
    ws.onclose = () => resolve()
    ws.onerror = () => reject(new Error('WebSocket error'))
  })
}
