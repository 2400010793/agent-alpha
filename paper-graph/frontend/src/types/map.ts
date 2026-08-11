import type { GraphResponse } from '../lib/api'

export type ResearchMap = {
  id: string
  title: string
  seed_ids: string[]
  paper_ids: string[]
  graph: GraphResponse
  created_at: string
  updated_at: string
}
