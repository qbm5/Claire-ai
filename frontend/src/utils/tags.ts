export const NO_TAG = '__no_tag__'

export function splitTags(raw: string): string[] {
  return raw.split(',').map(s => s.trim().toLowerCase()).filter(Boolean)
}
