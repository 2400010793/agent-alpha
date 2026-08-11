import type { PaperView } from '../types/paper'
import type { GraphEdgeView } from '../types/graph'

export function forceLayout(papers: PaperView[], edges: GraphEdgeView[], iterations = 160): PaperView[] {
  const nodes = papers.map((paper, index) => ({ ...paper, x: paper.role === 'seed' ? 50 : 50 + Math.cos(index * 2.4) * 28, y: paper.role === 'seed' ? 50 : 50 + Math.sin(index * 2.4) * 28, vx: 0, vy: 0 }))
  const byId = new Map(nodes.map((node) => [node.id, node]))
  for (let tick = 0; tick < iterations; tick += 1) {
    const alpha = Math.max(.08, 1 - tick / iterations)
    for (let i = 0; i < nodes.length; i += 1) for (let j = i + 1; j < nodes.length; j += 1) {
      const a = nodes[i]; const b = nodes[j]; const dx = b.x - a.x; const dy = b.y - a.y; const distance = Math.max(Math.hypot(dx, dy), 1.5); const aRadius = a.role === 'seed' ? 10 : 4 + Math.sqrt(Math.max(a.citations, 0)) / 16; const bRadius = b.role === 'seed' ? 10 : 4 + Math.sqrt(Math.max(b.citations, 0)) / 16; const minimumDistance = aRadius + bRadius + 10; const overlapForce = distance < minimumDistance ? (minimumDistance - distance) * .16 : 0; const force = 78 * alpha / (distance * distance) + overlapForce
      a.vx -= dx / distance * force; a.vy -= dy / distance * force; b.vx += dx / distance * force; b.vy += dy / distance * force
    }
    edges.forEach((edge) => { const a = byId.get(edge.source); const b = byId.get(edge.target); if (!a || !b) return; const dx = b.x - a.x; const dy = b.y - a.y; const distance = Math.max(Math.hypot(dx, dy), .1); const ideal = edge.kind === 'similarity' ? 20 + (1 - edge.score) * 26 : edge.kind === 'author' ? 28 : 36; const force = (distance - ideal) * (edge.kind === 'similarity' ? .014 : edge.kind === 'author' ? .01 : .008) * alpha; a.vx += dx / distance * force; a.vy += dy / distance * force; b.vx -= dx / distance * force; b.vy -= dy / distance * force })
    nodes.forEach((node) => { if (node.role === 'seed') { node.x = 50; node.y = 50; node.vx = 0; node.vy = 0; return } node.vx += (50 - node.x) * .0015; node.vy += (50 - node.y) * .0015; node.x = Math.max(5, Math.min(95, node.x + node.vx)); node.y = Math.max(7, Math.min(93, node.y + node.vy)); node.vx *= .82; node.vy *= .82 })
  }
  return nodes.map(({ vx: _vx, vy: _vy, ...paper }) => paper)
}
