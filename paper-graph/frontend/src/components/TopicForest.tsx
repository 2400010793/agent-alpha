import { useMemo, useState } from 'react'

type ForestGraph = {
  graph_id: string
  topic_id: string
  path: string
  node_count: number
  edge_count: number
  seed_count: number
  expansion_count: number
  error_count: number
  graph: Record<string, unknown>
}

type ForestLeaf = {
  id: string
  label: string
  keywords: string[]
  candidate_count: number
  graph_count: number
  node_count: number
  edge_count: number
  graphs: ForestGraph[]
}

type ForestRoot = { id: string; label: string; children: ForestLeaf[] }
export type TopicForestData = {
  schema_version: string
  root_count: number
  leaf_count: number
  graph_count: number
  roots: ForestRoot[]
}

type Props = {
  data: TopicForestData
  onOpenGraph: (graph: ForestGraph, leaf: ForestLeaf) => void
}

export function TopicForest({ data, onOpenGraph }: Props) {
  const [selectedRoot, setSelectedRoot] = useState<string | null>(null)
  const [selectedLeaf, setSelectedLeaf] = useState<string | null>(null)
  const visibleRoots = useMemo(() => selectedRoot ? data.roots.filter((root) => root.id === selectedRoot) : data.roots, [data.roots, selectedRoot])
  const totalGraphs = data.graph_count
  const totalErrors = data.roots.reduce((total, root) => total + root.children.reduce((leafTotal, leaf) => leafTotal + leaf.graphs.reduce((graphTotal, graph) => graphTotal + graph.error_count, 0), 0), 0)
  const visibleGraphCount = visibleRoots.reduce((total, root) => total + root.children.reduce((leafTotal, leaf) => leafTotal + leaf.graph_count, 0), 0)

  return <section className="forest-view">
    <div className="forest-hero">
      <div>
        <div className="eyebrow">RESEARCH KNOWLEDGE FOREST</div>
        <h1>Paper Graph Forest</h1>
        <p>从一级主题森林，到二级主题叶节点，再到可展开的局部 graph。</p>
      </div>
      <div className="forest-kpis">
        <div><strong>{data.root_count}</strong><span>根主题</span></div>
        <div><strong>{data.leaf_count}</strong><span>二级主题</span></div>
        <div><strong>{totalGraphs}</strong><span>已生成 graph</span></div>
        <div className={totalErrors ? 'warning' : ''}><strong>{totalErrors}</strong><span>扩展问题</span></div>
      </div>
    </div>
    <div className="forest-toolbar">
      <span>MACRO VIEW · {selectedRoot ? '已筛选一级主题' : '全部主题'} · {visibleGraphCount} graphs</span>
      <button onClick={() => { setSelectedRoot(null); setSelectedLeaf(null) }}>显示全部森林</button>
    </div>
    <div className="forest-canvas">
      <div className="forest-trunk"><span /> Knowledge Forest <small>{data.root_count} first-level domains · {data.leaf_count} topic leaves</small></div>
      <div className="forest-roots">
        {visibleRoots.map((root) => <div className="forest-root" key={root.id}>
          <button className={`root-node ${selectedRoot === root.id ? 'active' : ''}`} onClick={() => { setSelectedRoot(root.id); setSelectedLeaf(null) }}>
            <span className="root-orbit" />{root.label}<small>{root.children.length} 个二级主题</small>
          </button>
          <div className="root-branch" />
          <div className="forest-leaves">
            {root.children.map((leaf) => <article className={`leaf-card ${selectedLeaf === leaf.id ? 'active' : ''}`} key={leaf.id}>
              <button className="leaf-heading" onClick={() => setSelectedLeaf(selectedLeaf === leaf.id ? null : leaf.id)}>
                <span className="leaf-dot" />
                <span><strong>{leaf.label}</strong><small>{leaf.id}</small></span>
                <em>{leaf.graph_count} graph</em>
              </button>
              {selectedLeaf === leaf.id && <div className="leaf-graphs">
                <div className="leaf-summary"><span>{leaf.candidate_count} 个候选关系</span><span>{leaf.node_count} 个节点</span><span>{leaf.edge_count} 条边</span></div>
                {leaf.graphs.length ? leaf.graphs.map((graph) => <button className="graph-leaf" key={graph.graph_id} onClick={() => onOpenGraph(graph, leaf)}>
                  <span className="graph-leaf-icon">G</span>
                  <span><strong>{graph.graph_id}{graph.error_count > 0 && <em className="graph-warning">{graph.error_count} issues</em>}</strong><small>{graph.node_count} nodes · {graph.edge_count} edges · {graph.seed_count} seeds</small></span>
                  <span className="graph-arrow">↗</span>
                </button>) : <div className="empty-leaf">当前没有符合严格 OpenAlex 条件的 graph</div>}
              </div>}
            </article>)}
          </div>
        </div>)}
      </div>
    </div>
  </section>
}
