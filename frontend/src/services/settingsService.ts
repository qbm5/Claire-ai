import type { Settings, CustomSettingsGroup, Model } from '@/models'
import { get, post, put, del } from './api'

export function getSettings(): Promise<Settings> {
  return get<Settings>('/settings')
}

export function saveSettings(settings: Partial<Settings>): Promise<{ response: string }> {
  return post<{ response: string }>('/settings', settings)
}

export function getCustomSettings(): Promise<CustomSettingsGroup[]> {
  return get<CustomSettingsGroup[]>('/settings/custom')
}

export function saveCustomSettings(
  settings: { resource_type: string; resource_id: string; name: string; value: string }[]
): Promise<{ response: string }> {
  return post<{ response: string }>('/settings/custom', settings)
}

export function getModels(): Promise<Model[]> {
  return get<Model[]>('/settings/models')
}

export function createModel(model: Partial<Model>): Promise<Model> {
  return post<Model>('/settings/models', model)
}

export function updateModel(id: string, model: Partial<Model>): Promise<Model> {
  return put<Model>(`/settings/models/${id}`, model)
}

export function deleteModel(id: string): Promise<void> {
  return del<void>(`/settings/models/${id}`)
}

export function reorderModels(ids: string[]): Promise<{ response: string }> {
  return put<{ response: string }>('/settings/models/reorder', { ids })
}
