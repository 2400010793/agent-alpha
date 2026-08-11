import type { PaperView } from '../types/paper'
import type { GraphEdgeView } from '../types/graph'
import { PaperNode } from './PaperNode'

type Props = { papers: PaperView[]; edges: GraphEdgeView[]; selectedId: string; onSelect: (id: string) => void; onGenerate?: (id: string) => void; onSeed?: (id: string) => void; onAdd?: (id: string) => void }

function isVerifiedDirectCitation(edge: GraphEdgeView): boolean {
	return edge.relation === 'CITES' && edge.metadata?.synthetic !== true && edge.metadata?.verified !== false
}

function nodeRadius(paper: PaperView): number {
	return paper.role === 'seed' ? 10 : 4 + Math.sqrt(Math.max(paper.citations, 0)) / 16
}

function shortenLine(source: PaperView, target: PaperView) {
	const dx = target.x - source.x
	const dy = target.y - source.y
	const distance = Math.max(Math.hypot(dx, dy), 0.001)
	const ux = dx / distance
	const uy = dy / distance
	const sourceOffset = nodeRadius(source)
	const targetOffset = nodeRadius(target) + 1.6
	return { x1: source.x + ux * sourceOffset, y1: source.y + uy * sourceOffset, x2: target.x - ux * targetOffset, y2: target.y - uy * targetOffset }
}

export function ForceGraph({ papers, edges, selectedId, onSelect, onGenerate, onSeed, onAdd }: Props) {
	const byId = new Map(papers.map((paper) => [paper.id, paper]))
	const selected = byId.get(selectedId)
	return <div className="force-graph-wrap"><div className="graph-legend"><span><i className="legend-dot seed-dot" />Seed</span><span><i className="legend-dot paper-dot" />Related papers</span><span><i className="legend-line citation-legend" />Verified citations</span><span><i className="legend-line similar-legend" />Similarity</span><span><i className="legend-line author-legend" />Authors</span></div><svg className="graph-canvas force-canvas" viewBox="0 0 100 100" role="img" aria-label="Literature relationship graph"><defs><marker id="citation-arrow" markerWidth="2.4" markerHeight="2.4" refX="2" refY="1.2" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L2.4,1.2 L0,2.4 z" fill="#e24b4b" /></marker></defs><rect width="100" height="100" fill="#fff" />{edges.map((edge, index) => { const source = byId.get(edge.source); const target = byId.get(edge.target); if (!source || !target) return null; const directCitation = isVerifiedDirectCitation(edge); const line = shortenLine(source, target); return <line key={`${edge.source}-${edge.target}-${edge.relation}-${index}`} {...line} className={`edge ${edge.kind}-edge ${directCitation ? 'verified-citation-edge' : ''}`} strokeWidth={edge.kind === 'citation' ? 1 : Math.max(.5, edge.score)} markerEnd={directCitation ? 'url(#citation-arrow)' : undefined} /> })}{papers.map((paper) => <PaperNode key={paper.id} paper={paper} selected={paper.id === selectedId} radius={paper.role === 'seed' ? 10 : 6 + Math.sqrt(Math.max(paper.citations, 0)) / 30} color={paper.role === 'seed' ? '#606b73' : 'transparent'} opacity={paper.role === 'seed' ? 1 : .24 + (Math.min(Math.max(paper.year - 1992, 0), 34) / 34) * .62} onSelect={onSelect} />)}</svg>{selected && <div className="graph-paper-popover"><div className="popover-kicker">{selected.role === 'seed' ? 'SEED PAPER' : 'SELECTED PAPER'}</div><strong>{selected.title}</strong><small>{selected.authors} · {selected.year} · {selected.citations.toLocaleString()} citations</small><div className="popover-actions"><button type="button" onClick={() => onGenerate?.(selected.id)}>Generate graph</button><button type="button" title="加入 Seed 列表，之后可用于 Build Seed Map" onClick={() => onSeed?.(selected.id)}>Add to seed list</button><button type="button" title="将论文及其关联文献追加到当前图谱" onClick={() => onAdd?.(selected.id)}>Add to current map</button></div></div>}</div>
}
