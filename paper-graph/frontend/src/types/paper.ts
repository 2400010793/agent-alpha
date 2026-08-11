import type { ApiPaper } from '../lib/api'

export type PaperRole = 'seed' | 'prior' | 'derivative' | 'related'

export type PaperView = {
  id: string
  title: string
  authors: string
  year: number
  citations: number
  similarity: number
  role: PaperRole
  x: number
  y: number
  abstract: string
  researchTopic: string
  review: 'pass' | 'review'
  recommendation: number
  digest?: NonNullable<NonNullable<ApiPaper['metadata']>['digest']>
}
