import { get } from './api'

export interface CommunityItem {
  id: string
  name: string
  description: string
  item_type: 'tool' | 'trigger' | 'pipeline'
  item_subtype: string
  author_name: string
  image_url: string
  download_count: number
  tags: string[]
  created_at: string
  version: number
  upvote_count: number
  downvote_count: number
}

export interface CommunityBrowseResult {
  items: CommunityItem[]
  total: number
  page: number
  limit: number
  pages: number
}

export interface CommunityDownload {
  config_json: Record<string, any>
  name: string
  item_type: string
}

export interface CommunityStatus {
  configured: boolean
  reachable: boolean
  url: string
}

export function getCommunityStatus(): Promise<CommunityStatus> {
  return get<CommunityStatus>('/community/status')
}

export function browseCommunityItems(params: {
  type?: string
  search?: string
  sort?: string
  page?: number
  limit?: number
}): Promise<CommunityBrowseResult> {
  const query = new URLSearchParams()
  if (params.type) query.set('type', params.type)
  if (params.search) query.set('search', params.search)
  if (params.sort) query.set('sort', params.sort || 'newest')
  if (params.page) query.set('page', String(params.page))
  if (params.limit) query.set('limit', String(params.limit))
  return get<CommunityBrowseResult>(`/community/items?${query.toString()}`)
}

export function downloadCommunityItem(itemId: string): Promise<CommunityDownload> {
  return get<CommunityDownload>(`/community/items/${itemId}/download`)
}
