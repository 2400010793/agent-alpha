export type ApiPaper = {
  id: string
  title: string
  authors: string[]
  year?: number
  citations?: number
  citation_count?: number
  global_impact?: number
  relevance_score?: number
  abstract?: string
  keywords?: string[]
  url?: string
  metadata?: {
    provider?: string
    doi?: string
    digest?: {
      research_topic?: string
      research_question?: string
      method?: string
      author_claim?: string
      evidence_status?: string
      limitations?: string
      critical_assessment?: string
      missing_validation?: string
      datasets?: string
      metrics?: string
      experiment_details?: string
      plain_language_takeaway?: string
      opinions?: Record<string, unknown>[]
      analysis_pipeline?: string
      analysis_agent?: string
      faithfulness_verdict?: string
      recommendation_score?: number
    }
  }
}

export type ApiAuthor = { id: string; name: string; paper_count?: number; citation_count?: number }

export type ApiNode = ApiPaper & {
  is_seed: boolean
  seed_ids?: string[]
  map_ids?: string[]
  relevance_score?: number
  doi?: string
  arxiv_id?: string
  venue?: string
  role: string
}

export type ApiEdge = {
  source: string
  target: string
  relation: 'CITES' | 'CITED_BY' | 'CITATION_SIMILAR_TO' | 'EMBEDDING_SIMILAR_TO' | 'AUTHOR_SHARED_BY'
  weight?: number
  confidence?: number
  metadata?: Record<string, unknown>
}

export type GraphResponse = {
  seed: string
  seed_ids?: string[]
  multi_seed?: boolean
  seed_title: string
  nodes: ApiNode[]
  edges: ApiEdge[]
  stats: { node_count: number; citation_edge_count: number; similarity_edge_count: number }
  source?: string
  filters?: { min_year?: number; year_weight?: number }
}

export type ApiHealth = { ok: boolean; api_version?: string; graph_sample?: boolean; graph_sample_path?: string; local_papers: number; local_edges: number; semantic_scholar_cached_requests: number; sources: string[] }
export type ApiReady = { ready: boolean; api_version: string; graph_sample: boolean }

export type ResearchMap = {
  id: string
  title: string
  seed_ids: string[]
  paper_ids: string[]
  graph: GraphResponse
  created_at: string
  updated_at: string
  query?: string
  filters?: Record<string, unknown>
}

const api = async <T,>(path: string, options?: RequestInit): Promise<T> => {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) } })
  if (!response.ok) {
    let detail = ''
    try { detail = String((await response.json()).detail || '') } catch { /* non-JSON error */ }
    throw new Error(detail || `API request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const searchPapers = (query: string) => api<{ results: ApiPaper[] }>(`/api/search?q=${encodeURIComponent(query)}`)
export const discoverPapers = (query: string) => api<{ results: ApiPaper[] }>(`/api/discovery/search?q=${encodeURIComponent(query)}&limit=40`)
export const searchAuthors = (query: string) => api<{ results: ApiAuthor[] }>(`/api/authors/search?q=${encodeURIComponent(query)}&limit=20`)
export const fetchAuthorPapers = (authorId: string, offset = 0) => api<{ results: ApiPaper[]; offset: number; limit: number }>(`/api/authors/${encodeURIComponent(authorId)}/papers?limit=40&offset=${offset}`)
export const fetchGraph = (paperId: string, expandLimit = 40) => api<GraphResponse>(`/api/graphs/${encodeURIComponent(paperId)}?expand_limit=${expandLimit}`)
export type ArxivAvailability = { paper_id: string; arxiv_id?: string | null; arxiv_url?: string | null; arxiv_pdf_url?: string | null; arxiv_location?: boolean; status: 'linked' | 'not_found' | 'lookup_failed'; error?: string }
export const fetchArxivAvailability = (paperIds: string[]) => api<{ results: ArxivAvailability[]; queried: number }>(`/api/arxiv-availability?ids=${encodeURIComponent(paperIds.join(','))}`)
export const fetchRealizedVolatilityGraph = (limit = 40) => api<GraphResponse>(`/api/graphs/realized-volatility?limit=${limit}`)
export const fetchPaper = (paperId: string) => api<ApiPaper>(`/api/papers/${encodeURIComponent(paperId)}`)
export const buildSeedMap = (seedIds: string[], filters?: { min_year?: number; year_weight?: number }) => api<GraphResponse>('/api/graphs/seed-map', { method: 'POST', body: JSON.stringify({ seed_ids: seedIds, ...(filters || {}) }) })
export const queuePaperForParsing = (paper: ApiPaper, reason = 'manual') => api<{ paper_id: string; status: string }>('/api/papers/parse-queue', { method: 'POST', body: JSON.stringify({ paper, reason }) })
export const addTopicSeed = (topicId: string, seedId: string, options?: { expand_limit?: number; embedding_threshold?: number }) => api<GraphResponse & { decision?: 'merge' | 'new_graph'; variant_id?: string; decision_basis?: string }>('/api/topic-graphs/' + encodeURIComponent(topicId) + '/seeds', { method: 'POST', body: JSON.stringify({ seed_id: seedId, ...(options || {}) }) })
export const fetchHealth = () => api<ApiHealth>('/api/health')
export const fetchReady = () => api<ApiReady>('/api/ready')
export const listMaps = () => api<{ results: ResearchMap[] }>('/api/maps')
export const saveMap = (payload: { title: string; seed_ids: string[]; graph: GraphResponse }) => api<ResearchMap>('/api/maps', { method: 'POST', body: JSON.stringify(payload) })
export const deleteMap = (mapId: string) => api<{ ok: boolean }>(`/api/maps/${encodeURIComponent(mapId)}`, { method: 'DELETE' })
export const copyMap = (mapId: string) => api<ResearchMap>(`/api/maps/${encodeURIComponent(mapId)}/copy`, { method: 'POST' })
export const overlapMaps = (mapIds: string[]) => api<{ intersection: ApiPaper[]; bridge_papers: ApiPaper[]; gaps: string[] }>('/api/maps/overlap', { method: 'POST', body: JSON.stringify({ map_ids: mapIds }) })