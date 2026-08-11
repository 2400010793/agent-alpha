import type { ApiPaper } from './api'

export function mergeSearchResults(...groups: ApiPaper[][]): ApiPaper[] { return [...new Map(groups.flat().map((paper) => [paper.id, paper])).values()] }
export function filterPapers(papers: ApiPaper[], query: string): ApiPaper[] { const terms = query.toLocaleLowerCase().split(/\s+/).filter(Boolean); return papers.filter((paper) => { const text = `${paper.title} ${paper.authors.join(' ')} ${paper.abstract || ''} ${(paper.keywords || []).join(' ')}`.toLocaleLowerCase(); return terms.every((term) => text.includes(term)) }) }
