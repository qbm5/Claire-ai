import { post } from './api'

export async function saveOrder(table: string, ids: string[]): Promise<void> {
  await post(`/${table}/reorder`, { ids })
}
