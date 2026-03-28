export function parseKv(raw: any): { key: string; value: string }[] {
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (typeof raw === 'object' && raw !== null) {
    return Object.entries(raw).map(([key, value]) => ({ key, value: String(value) }))
  }
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed
      if (typeof parsed === 'object' && parsed !== null) {
        return Object.entries(parsed).map(([key, value]) => ({ key, value: String(value) }))
      }
    } catch {}
  }
  return []
}

export function serializeKv(pairs: { key: string; value: string }[]): string {
  return pairs.length ? JSON.stringify(pairs) : ''
}
