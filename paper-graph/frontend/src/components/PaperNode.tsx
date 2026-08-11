import type { PaperView } from '../types/paper'

export function PaperNode({ paper, selected, radius, color, opacity, onSelect }: { paper: PaperView; selected: boolean; radius: number; color: string; opacity: number; onSelect: (id: string) => void }) {
	const visualRadius = paper.role === 'seed' ? radius : 4 + Math.sqrt(Math.max(paper.citations, 0)) / 16
	return <g className={`paper-node role-${paper.role} ${selected ? 'selected' : ''}`} onClick={() => onSelect(paper.id)} transform={`translate(${paper.x} ${paper.y})`}><circle r={visualRadius} fill={color} fillOpacity={opacity} /><text y={visualRadius + 3.3} textAnchor="middle" className="node-label">{paper.title.split(' ').slice(0, 3).join(' ')}</text></g>
}
