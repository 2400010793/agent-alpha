import type { PaperView } from '../types/paper'

export type TimelinePoint = PaperView & { fixed?: boolean }

export function timelineLayout(papers: PaperView[], width = 1000, height = 600): TimelinePoint[] {
  const years = papers.map((paper) => paper.year).filter((year) => Number.isFinite(year) && year > 0)
  const dataMinYear = years.length ? Math.min(...years) : 2000
  const dataMaxYear = years.length ? Math.max(...years) : dataMinYear + 1
  const minYear = dataMinYear === dataMaxYear ? dataMinYear - 1 : dataMinYear
  const maxImpact = Math.max(...papers.map((paper) => paper.citations), 1)
    const groups = new Map<number, number>()
  const maxYear = dataMinYear === dataMaxYear ? dataMaxYear + 1 : dataMaxYear
  const yearSpan = Math.max(maxYear - minYear, 1)
  const points: TimelinePoint[] = papers.map((paper) => { const year = paper.year || minYear; const index = groups.get(year) || 0; groups.set(year, index + 1); const count = Math.max(1, Math.ceil(Math.sqrt(papers.filter((item) => (item.year || minYear) === year).length))); const row = Math.floor(index / count); return { ...paper, x: 75 + ((year - minYear) / yearSpan) * (width - 150), y: height - 170 - Math.sqrt(Math.max(paper.citations, 0) / maxImpact) * (height - 320) + row * 115 } })
  for (let iteration = 0; iteration < 42; iteration += 1) { for (let i = 0; i < points.length; i += 1) for (let j = i + 1; j < points.length; j += 1) { const left = points[i]; const right = points[j]; const dx = right.x - left.x; const dy = right.y - left.y; const distance = Math.max(Math.hypot(dx, dy), .1); const leftRadius = left.role === 'seed' ? 75 : 22 + Math.sqrt(Math.max(left.citations, 0)) / 3; const rightRadius = right.role === 'seed' ? 75 : 22 + Math.sqrt(Math.max(right.citations, 0)) / 3; const minimumDistance = leftRadius + rightRadius + 38; if (distance >= minimumDistance) continue; const verticalSign = dy === 0 ? (i % 2 ? 1 : -1) : Math.sign(dy); const push = (minimumDistance - distance) * .42; if (!left.fixed) left.y -= verticalSign * push; if (!right.fixed) right.y += verticalSign * push } points.forEach((point) => { const radius = point.role === 'seed' ? 75 : 22 + Math.sqrt(Math.max(point.citations, 0)) / 3; point.x = 75 + (((point.year || minYear) - minYear) / yearSpan) * (width - 150); point.y = Math.max(radius + 15, Math.min(height - radius - 15, point.y)) }) }
    return points
}
