import type { GraphResponse } from './api'
import type { GraphEdgeView } from '../types/graph'
import type { PaperView } from '../types/paper'

export function graphToPaperViews(graph: GraphResponse): { papers: PaperView[]; edges: GraphEdgeView[] } {
  const papers = graph.nodes.map((node, index) => { const seed = node.is_seed || node.id === graph.seed; const digest = node.metadata?.digest; return { id: node.id, title: node.title, authors: node.authors.join(' · '), year: node.year ?? 0, citations: node.citation_count ?? 0, similarity: seed ? 1 : 0, role: (seed ? 'seed' : node.role === 'prior' || node.role === 'derivative' ? node.role : 'related') as PaperView['role'], x: seed ? 50 : 50 + Math.cos(index * 2.4) * 28, y: seed ? 50 : 50 + Math.sin(index * 2.4) * 28, abstract: node.abstract || digest?.plain_language_takeaway || '暂无摘要。', researchTopic: digest?.research_topic || '未提供研究主题', review: digest?.faithfulness_verdict === 'pass' ? 'pass' as const : 'review' as const, recommendation: Number(digest?.recommendation_score || 0), digest } })
  const edges = graph.edges.map((edge) => ({ source: edge.source, target: edge.target, kind: edge.relation === 'AUTHOR_SHARED_BY' ? 'author' as const : edge.relation === 'CITES' || edge.relation === 'CITED_BY' || edge.relation === 'CITATION_SIMILAR_TO' ? 'citation' as const : 'similarity' as const, score: edge.weight ?? 0, relation: edge.relation, confidence: edge.confidence, metadata: edge.metadata }))
  return { papers, edges }
}
