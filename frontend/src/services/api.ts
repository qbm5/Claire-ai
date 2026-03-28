const API_BASE = '/api'
const WS_BASE = `ws://${window.location.host}/ws`

function getToken(): string {
  return localStorage.getItem('auth_token') || ''
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const res = await fetch(`${API_BASE}${path}`, {
    headers,
    ...options,
  })

  if (res.status === 401) {
    // Token expired or invalid — redirect to login if auth is enabled
    const authToken = getToken()
    if (authToken) {
      localStorage.removeItem('auth_token')
      window.location.href = '/login'
    }
  }

  return res.json()
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path)
}

export function post<T>(path: string, body: any): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) })
}

export function put<T>(path: string, body: any): Promise<T> {
  return request<T>(path, { method: 'PUT', body: JSON.stringify(body) })
}

export function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' })
}

export async function uploadFile<T = any>(path: string, file: File, fieldName = 'file'): Promise<T> {
  const form = new FormData()
  form.append(fieldName, file)
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', body: form, headers })
  return res.json()
}

export function wsConnect(path: string): WebSocket {
  const token = getToken()
  const sep = path.includes('?') ? '&' : '?'
  const url = token ? `${WS_BASE}${path}${sep}token=${token}` : `${WS_BASE}${path}`
  return new WebSocket(url)
}

/**
 * Fetch an image URL and return it as a base64 data URI.
 * Returns empty string if the fetch fails or there's no URL.
 */
export async function imageUrlToBase64(url: string): Promise<string> {
  if (!url) return ''
  try {
    const fullUrl = url.startsWith('/') ? `${window.location.origin}${url}` : url
    const resp = await fetch(fullUrl)
    if (!resp.ok) return ''
    const blob = await resp.blob()
    return new Promise((resolve) => {
      const reader = new FileReader()
      reader.onloadend = () => resolve(reader.result as string)
      reader.onerror = () => resolve('')
      reader.readAsDataURL(blob)
    })
  } catch {
    return ''
  }
}

export { API_BASE, WS_BASE }
