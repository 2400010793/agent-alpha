export type GraphRelation = 'citation' | 'similarity' | 'author'
export type SourceGraphRelation = 'CITES' | 'CITED_BY' | 'CITATION_SIMILAR_TO' | 'EMBEDDING_SIMILAR_TO' | 'AUTHOR_SHARED_BY'

export type GraphEdgeView = {
  source: string
  target: string
  kind: GraphRelation
  score: number
  relation?: SourceGraphRelation
  confidence?: number
  metadata?: Record<string, unknown>
}

export type LayoutMode = 'force' | 'timeline'
