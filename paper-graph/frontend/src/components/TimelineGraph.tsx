import { useMemo, useRef, useState } from 'react'
import type { PaperView } from '../types/paper'
import type { GraphEdgeView } from '../types/graph'
import { timelineLayout, type TimelinePoint } from '../lib/timelineLayout'
import { TimelineAxis } from './TimelineAxis'
import { ImpactAxis } from './ImpactAxis'

const WIDTH = 1000
const HEIGHT = 600

type TimelineProps = {
  papers: PaperView[]
  edges: GraphEdgeView[]
  seedIds: string[]
  selectedId?: string
  onSelect: (id: string) => void
  onClearSelection?: () => void
}

function curvePath(source: TimelinePoint, target: TimelinePoint, lane: number): string {
  const dx = target.x - source.x
  const dy = target.y - source.y
  const distance = Math.max(Math.hypot(dx, dy), 1)
  const bend = Math.min(150, Math.max(34, distance * .24)) * lane
  const controlX = (source.x + target.x) / 2 - (dy / distance) * bend
  const controlY = (source.y + target.y) / 2 + (dx / distance) * bend
  return `M ${source.x} ${source.y} Q ${controlX} ${controlY} ${target.x} ${target.y}`
}

export function TimelineGraph({ papers, edges, seedIds, selectedId, onSelect, onClearSelection }: TimelineProps) {
  const [points, setPoints] = useState<TimelinePoint[]>(() => timelineLayout(papers, WIDTH, HEIGHT))
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const drag = useRef<{ id: string; x: number; y: number } | null>(null)
  const graphKey = papers.map((paper) => paper.id).join('|')
  const layout = useMemo(() => timelineLayout(papers, WIDTH, HEIGHT), [graphKey, papers])
  const current = points.length === papers.length && points.every((point, index) => point.id === papers[index]?.id) ? points : layout
  const byId = new Map(current.map((point) => [point.id, point]))
  // Selecting one of several seed papers must not hide the other seed
  // neighborhoods. Only a non-seed selection enters the one-paper focus mode.
  const focusId = selectedId && !seedIds.includes(selectedId) ? selectedId : undefined
  const visibleEdges = edges.filter((edge) => focusId ? edge.source === focusId || edge.target === focusId : seedIds.includes(edge.source) || seedIds.includes(edge.target))
  const pairCounts = new Map<string, number>()
  const onWheel = (event: React.WheelEvent<SVGSVGElement>) => { event.preventDefault(); setZoom((value) => Math.max(.55, Math.min(3.2, value * (event.deltaY < 0 ? 1.12 : .9)))) }
  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!drag.current) return
    const dx = event.clientX - drag.current.x
    const dy = event.clientY - drag.current.y
    if (drag.current.id === '__pan__') { setPan((value) => ({ x: value.x + dx, y: value.y + dy })); drag.current = { id: '__pan__', x: event.clientX, y: event.clientY }; return }
    const point = byId.get(drag.current.id)
    if (!point) return
    setPoints(current.map((item) => item.id === point.id ? { ...item, x: item.x + dx / zoom, y: item.y + dy / zoom, fixed: true } : item))
    drag.current = { id: point.id, x: event.clientX, y: event.clientY }
  }
  const startPan = (event: React.PointerEvent<SVGSVGElement>) => { if (event.target === event.currentTarget) { event.currentTarget.setPointerCapture(event.pointerId); drag.current = { id: '__pan__', x: event.clientX, y: event.clientY } } }
  const stopDrag = () => { drag.current = null }

  const seedLabel = seedIds.length > 1 ? `${seedIds.length} 个 Seed` : 'Seed'
  const relationLabel = focusId ? '当前论文一阶关系' : `${seedLabel}关系`
  return <div className="timeline-graph"><div className="timeline-legend"><span><i className="timeline-legend-line citation-legend" />直接引用（箭头）</span><span><i className="timeline-legend-line similar-legend" />引用/语义相似</span><span><i className="timeline-legend-line author-legend" />共同作者</span>{seedIds.length > 1 && <button className="timeline-reset" type="button" onClick={onClearSelection}>{focusId ? `显示全部 ${seedLabel}` : `正在显示全部 ${seedLabel}`}</button>}</div><ImpactAxis label="Citation count" /><svg className="graph-canvas timeline-canvas" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} onWheel={onWheel} onPointerDown={startPan} onPointerMove={onPointerMove} onPointerUp={stopDrag} onPointerLeave={stopDrag} onClick={(event) => { if (event.target === event.currentTarget) onClearSelection?.() }}><g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`}><defs><marker id="timeline-arrow" markerWidth="8" markerHeight="8" refX="6.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#e24b4b" /></marker></defs>{visibleEdges.map((edge, index) => { const source = byId.get(edge.source); const target = byId.get(edge.target); if (!source || !target) return null; const pair = [edge.source, edge.target].sort().join('|'); const pairIndex = pairCounts.get(pair) || 0; pairCounts.set(pair, pairIndex + 1); const isDirectCitation = edge.relation === 'CITES' && edge.metadata?.synthetic !== true && edge.metadata?.verified !== false; const baseLane = edge.kind === 'author' ? 1.45 : isDirectCitation ? -1.45 : edge.kind === 'citation' ? -.55 : .8; const lane = baseLane + (pairIndex % 2) * .32; const sharedAuthors = edge.metadata?.shared_authors; const sharedCount = Array.isArray(sharedAuthors) ? sharedAuthors.length : edge.metadata?.shared_author_count; const title = edge.kind === 'author' ? `共同作者关系${typeof sharedCount === 'number' ? ` · ${sharedCount} 位共同作者` : ''}` : isDirectCitation ? (edge.relation === 'CITED_BY' ? '被引用关系' : '引用关系') : edge.kind === 'citation' ? '引用结构相似关系' : '语义相似关系'; return <path key={`${edge.source}-${edge.target}-${edge.kind}-${index}`} d={curvePath(source, target, lane)} className={`edge ${edge.kind}-edge`} markerEnd={isDirectCitation ? 'url(#timeline-arrow)' : undefined}><title>{title}</title></path> })}{current.map((paper) => <g key={paper.id} className={`timeline-node role-${paper.role} ${focusId === paper.id ? 'selected' : ''}`} onPointerDown={(event) => { event.stopPropagation(); event.currentTarget.setPointerCapture(event.pointerId); drag.current = { id: paper.id, x: event.clientX, y: event.clientY } }} onClick={() => onSelect(paper.id)}><circle cx={paper.x} cy={paper.y} r={paper.role === 'seed' ? 55 : Math.max(30, 20 + Math.sqrt(Math.max(paper.citations, 0)) / 8)} /><text x={paper.x} y={paper.y + 72} textAnchor="middle" className="node-label">{paper.title.split(' ').slice(0, 3).join(' ')}</text></g>)}</g></svg><TimelineAxis minYear={Math.min(...papers.map((paper) => paper.year), 2000)} maxYear={Math.max(...papers.map((paper) => paper.year), 2001)} /><small className="timeline-hint">{relationLabel} · 点击节点聚焦 · 滚轮缩放 · 拖动平移/节点</small></div>
}
