type Listener = (data: any) => void

const listeners = new Map<string, Set<Listener>>()
let eventSource: EventSource | null = null

export function connectSSE() {
  if (eventSource) return
  const token = localStorage.getItem('auth_token') || ''
  const url = token ? `/api/events?token=${token}` : '/api/events'
  eventSource = new EventSource(url)
  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      const type = data.type as string
      const cbs = listeners.get(type)
      if (cbs) {
        cbs.forEach(cb => cb(data))
      }
      // Also emit to wildcard listeners
      const all = listeners.get('*')
      if (all) {
        all.forEach(cb => cb(data))
      }
    } catch {}
  }
  eventSource.onerror = () => {
    eventSource?.close()
    eventSource = null
    // Reconnect after 3s
    setTimeout(connectSSE, 3000)
  }
}

export function disconnectSSE() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

export function onEvent(type: string, cb: Listener): () => void {
  if (!listeners.has(type)) listeners.set(type, new Set())
  listeners.get(type)!.add(cb)
  return () => listeners.get(type)?.delete(cb)
}

export function offEvent(type: string, cb: Listener) {
  listeners.get(type)?.delete(cb)
}
