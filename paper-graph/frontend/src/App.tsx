import { useEffect, useMemo, useRef, useState } from 'react'
import { buildSeedMap, copyMap, deleteMap, fetchArxivAvailability, fetchGraph, fetchHealth, fetchRealizedVolatilityGraph, listMaps, overlapMaps, queuePaperForParsing, saveMap, searchPapers, type ApiPaper, type GraphResponse, type ResearchMap } from './lib/api'
import { SearchBar } from './components/SearchBar'
import { GraphToolbar } from './components/GraphToolbar'
import { ForceGraph } from './components/ForceGraph'
import { TimelineGraph } from './components/TimelineGraph'
import { MapSelector } from './components/MapSelector'
import { OverlapLegend } from './components/OverlapLegend'
import { SeedSelector } from './components/SeedSelector'
import { PaperDetails } from './components/PaperDetails'
import { TopicForest, type TopicForestData } from './components/TopicForest'
import { filterPapers } from './lib/search'
import type { GraphEdgeView } from './types/graph'

type Paper = {
  id: string
  title: string
  authors: string
  year: number
  citations: number
  similarity: number
  role: 'seed' | 'prior' | 'derivative' | 'related'
  x: number
  y: number
  abstract: string
  researchTopic: string
  review: 'pass' | 'review'
  recommendation: number
  selectionScore: number
  keywords: string[]
  url?: string
  doi?: string
  arxivId?: string
  provider?: string
  discoveryMethods: string[]
  digest?: NonNullable<NonNullable<ApiPaper['metadata']>['digest']>
}

type Edge = { source: string; target: string; kind: 'citation' | 'similarity' | 'author'; score: number; relation?: GraphEdgeView['relation']; metadata?: Record<string, unknown> }

function useForceLayout(inputPapers: Paper[], inputEdges: Edge[]): Paper[] {
  const [layout, setLayout] = useState(inputPapers)
  const graphKey = `${inputPapers.map((paper) => paper.id).join('|')}:${inputEdges.map((edge) => `${edge.source}-${edge.target}-${edge.kind}-${edge.score}`).join('|')}`

  useEffect(() => {
    const seedCount = inputPapers.filter((paper) => paper.role === 'seed').length
    const seedRadius = seedCount > 1 ? Math.min(26, 14 + seedCount * 2.4) : 0
    const nodes = inputPapers.map((paper, index) => {
      const seedIndex = inputPapers.slice(0, index).filter((item) => item.role === 'seed').length
      const seedAngle = seedCount > 1 ? (seedIndex / seedCount) * Math.PI * 2 - Math.PI / 2 : 0
      const seedX = seedCount > 1 ? 50 + Math.cos(seedAngle) * seedRadius : 50
      const seedY = seedCount > 1 ? 50 + Math.sin(seedAngle) * seedRadius : 50
      return {
      ...paper,
      x: paper.role === 'seed' ? seedX : 50 + Math.cos(index * 2.4) * 22,
      y: paper.role === 'seed' ? seedY : 50 + Math.sin(index * 2.4) * 22,
      seedX,
      seedY,
      vx: 0,
      vy: 0,
      }
    })
    const byId = new Map(nodes.map((node) => [node.id, node]))
    let frame = 0
    let tick = 0
    let animationFrame = 0

    const simulate = () => {
      const alpha = Math.max(0.08, 1 - tick / 180)
      for (let i = 0; i < nodes.length; i += 1) {
        for (let j = i + 1; j < nodes.length; j += 1) {
          const left = nodes[i]
          const right = nodes[j]
          const dx = right.x - left.x
          const dy = right.y - left.y
          const distance = Math.max(Math.hypot(dx, dy), 1.5)
          const leftRadius = left.role === 'seed' ? 10 : 4 + Math.sqrt(Math.max(left.citations, 0)) / 16
          const rightRadius = right.role === 'seed' ? 10 : 4 + Math.sqrt(Math.max(right.citations, 0)) / 16
          const minimumDistance = leftRadius + rightRadius + 10
          const overlapForce = distance < minimumDistance ? (minimumDistance - distance) * 0.16 : 0
          const force = (78 * alpha) / (distance * distance) + overlapForce
          const fx = (dx / distance) * force
          const fy = (dy / distance) * force
          left.vx -= fx
          left.vy -= fy
          right.vx += fx
          right.vy += fy
        }
      }
      inputEdges.forEach((edge) => {
        const source = byId.get(edge.source)
        const target = byId.get(edge.target)
        if (!source || !target) return
        const dx = target.x - source.x
        const dy = target.y - source.y
        const distance = Math.max(Math.hypot(dx, dy), 0.1)
        const ideal = edge.kind === 'similarity' ? 20 + (1 - edge.score) * 26 : edge.kind === 'author' ? 28 : 36
        const force = (distance - ideal) * (edge.kind === 'similarity' ? 0.014 : edge.kind === 'author' ? 0.01 : 0.008) * alpha
        const fx = (dx / distance) * force
        const fy = (dy / distance) * force
        source.vx += fx
        source.vy += fy
        target.vx -= fx
        target.vy -= fy
      })
      nodes.forEach((node) => {
        const isSeed = node.role === 'seed'
        if (!isSeed) {
          node.vx += (50 - node.x) * 0.003
          node.vy += (50 - node.y) * 0.003
          node.x = Math.max(12, Math.min(88, node.x + node.vx))
          node.y = Math.max(14, Math.min(86, node.y + node.vy))
          node.vx *= 0.82
          node.vy *= 0.82
        } else {
          node.x = node.seedX
          node.y = node.seedY
          node.vx = 0
          node.vy = 0
        }
      })
      tick += 1
      if (frame % 2 === 0) setLayout(nodes.map(({ vx: _vx, vy: _vy, ...paper }) => paper))
      frame += 1
      if (tick < 180) animationFrame = requestAnimationFrame(simulate)
    }

    setLayout(inputPapers)
    animationFrame = requestAnimationFrame(simulate)
    return () => cancelAnimationFrame(animationFrame)
    // graphKey intentionally resets the simulation whenever the graph changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphKey])

  return layout
}

type AiAnalysis = {
  tldr: string
  contribution: string
  method: string
  limitations: string
  tags: string[]
  question: string
  evidence: string
  dataset: string
  ideas: { title: string; level: string; evidence: string }[]
}

const demoTitles = [
  'Modeling and Forecasting Realized Volatility', 'Realized Variance and Market Microstructure Noise', 'The HAR-RV Model for Volatility Forecasting', 'Realized Volatility Forecasting with Jumps', 'High-Frequency Volatility Forecasting with Neural Networks', 'A Review of Realized Volatility Measures', 'Forecasting Realized Volatility with Option-Implied Measures', 'Realized Kernels for Measuring Volatility', 'Multipower Variation and Volatility Jumps', 'Realized Volatility and the Information Content of Order Flow', 'Forecasting Volatility with Realized Measures and GARCH', 'Intraday Patterns in Realized Volatility', 'Robust Estimation of Integrated Variance', 'Realized Semivariances and Asymmetric Volatility', 'Noise-Robust Realized Volatility Estimation', 'Long Memory in Realized Volatility', 'Realized Volatility and Macroeconomic Announcements', 'Forecasting Volatility with Realized Quarticity', 'High-Frequency Data and Volatility Spillovers', 'Multivariate Realized Volatility Models', 'Realized Covariance and Portfolio Risk', 'Dynamic Conditional Correlation with Realized Measures', 'Option-Implied and Realized Volatility', 'Volatility Forecasting across Asset Classes', 'Machine Learning for Realized Volatility', 'Transformer Models for Intraday Volatility', 'Deep Learning with Limit Order Book Data', 'Forecasting Volatility under Market Stress', 'Realized Volatility and Tail Risk', 'Jump-Robust Volatility Forecasts', 'Bayesian Models for Realized Volatility', 'Nowcasting Volatility from High-Frequency Data', 'Realized Volatility in Cryptocurrency Markets', 'Forecasting Volatility with Mixed Frequencies', 'Functional Data Methods for Intraday Volatility', 'Volatility Measurement with Irregular Sampling', 'Realized Volatility and Liquidity', 'Factor Models for Realized Covariance', 'Economic Value of Volatility Forecasts', 'A Survey of High-Frequency Volatility Research',
]

demoTitles.push(
  'Realized Volatility under Market Frictions', 'Robust Intraday Covariance Estimation', 'Volatility Forecasting with Order Imbalance', 'High-Frequency Volatility and Price Discovery', 'Realized Measures for Portfolio Allocation', 'Nonparametric Volatility Forecasting', 'Volatility Jumps and News Announcements', 'Sparse Models for Realized Covariance', 'Realized Volatility with Missing Observations', 'Forecasting Volatility across Markets', 'Intraday Volatility Seasonality', 'Microstructure Noise and Sampling Frequency', 'Realized Measures in Illiquid Markets', 'Volatility Forecasting with Alternative Data', 'Deep Volatility Models with Attention', 'Realized Correlation and Systemic Risk', 'Multiscale Volatility Measurement', 'Bayesian Realized Volatility Models', 'Volatility Forecasting with Regime Switching', 'Robust Realized Covariance under Noise', 'High-Frequency Volatility and Liquidity', 'Realized Volatility for Risk Management', 'Cross-Asset Volatility Spillovers', 'Forecasting Volatility with Limit Order Books', 'Jump Detection in High-Frequency Prices', 'Realized Volatility and Market Stress', 'Functional Forecasting of Volatility', 'Volatility Measures for Derivatives Pricing', 'Long-Horizon Realized Volatility Forecasts', 'Realized Volatility and Trading Activity', 'Machine Learning for Volatility Jumps', 'Intraday Risk Forecasting with Realized Measures', 'Network Models of Realized Volatility', 'Volatility Forecasting with Mixed Data', 'High-Dimensional Realized Covariance', 'Realized Volatility and Investor Attention', 'Forecasting Volatility with Text Data', 'Robust Volatility Estimation for Crypto Assets', 'Realized Volatility and Monetary Policy', 'Volatility Forecasting with Ensembles', 'A Benchmark of Realized Volatility Estimators',
)

const papers: Paper[] = demoTitles.map((title, index) => {
  const seed = index === 0
  const year = seed ? 2003 : 1998 + ((index * 3) % 27)
  const citations = seed ? 3120 : Math.max(34, 2180 - index * 49)
  const angle = (index / demoTitles.length) * Math.PI * 2
  const similarity = seed ? 1 : Math.max(.53, .96 - index * .0052)
  const explicitCitation = index % 4 === 0
  const sourceAgreement = index % 5 === 0 ? 3 : index % 2 === 0 ? 2 : 1
  const selectionScore = seed ? 1 : similarity * .58 + Math.min(citations / 2400, 1) * .16 + (explicitCitation ? .16 : 0) + sourceAgreement * .033
  return { id: seed ? 'seed' : `p${index}`, title, authors: index % 3 === 0 ? 'T. Andersen · T. Bollerslev' : index % 3 === 1 ? 'C. Corsi · F. Diebold' : 'A. Aït-Sahalia · R. Todorov', year, citations, similarity, selectionScore, keywords: ['Realized volatility', 'High frequency'], discoveryMethods: ['demo'], role: seed ? 'seed' : 'related', x: seed ? 50 : 50 + Math.cos(angle) * 38, y: seed ? 48 : 48 + Math.sin(angle) * 38, abstract: `This realized-volatility study examines ${title.toLowerCase()} using high-frequency returns and evaluates implications for volatility measurement or forecasting.`, researchTopic: index % 3 === 0 ? 'Realized volatility · 高频计量' : index % 3 === 1 ? '波动率预测 · 时间序列' : '高频数据 · 风险测量', review: index % 7 === 0 ? 'review' : 'pass', recommendation: Math.max(6.1, 9.4 - index * .04) }
})

const edges: Edge[] = papers.slice(1).flatMap((paper, index): Edge[] => [
  { source: 'seed', target: paper.id, kind: 'similarity' as const, relation: index % 3 === 0 ? 'CITATION_SIMILAR_TO' : 'EMBEDDING_SIMILAR_TO', score: paper.similarity, metadata: { synthetic: true, source: 'demo' } },
  ...(index > 0 ? [{ source: paper.id, target: papers[index].id, kind: 'similarity' as const, relation: index % 4 === 0 ? 'CITATION_SIMILAR_TO' as const : 'EMBEDDING_SIMILAR_TO' as const, score: Math.max(.45, paper.similarity - .08), metadata: { synthetic: true, source: 'demo' } }] : []),
]).concat(papers.slice(1).filter((_, index) => index % 3 === 0).map((paper) => ({ source: 'seed', target: paper.id, kind: 'author' as const, relation: 'AUTHOR_SHARED_BY' as const, score: 1 })))

const roleLabel = { seed: 'SEED PAPER', prior: 'PRIOR WORK', derivative: 'DERIVATIVE', related: 'RELATED' }

function paperLink(paper: Pick<Paper, 'id' | 'url' | 'doi' | 'arxivId'>): { label: string; href: string } | null {
  const arxivId = paper.arxivId || paper.id.match(/^arxiv:(.+)$/i)?.[1]
  if (arxivId) return { label: 'arXiv 页面', href: `https://arxiv.org/abs/${arxivId}` }
  if (paper.doi) return { label: 'DOI 页面', href: paper.doi.startsWith('http') ? paper.doi : `https://doi.org/${paper.doi}` }
  if (paper.url && /^https?:\/\//i.test(paper.url)) return { label: '来源页面', href: paper.url }
  return null
}

function graphToDemoShape(graph: GraphResponse): { papers: Paper[]; edges: Edge[] } {
  const nodes = graph.nodes
  const papers = nodes.map((node, index) => {
    const angle = (index / Math.max(nodes.length, 1)) * Math.PI * 2
    const graphSeedIds = graph.seed_ids || [graph.seed]
    const isSeed = node.is_seed || graphSeedIds.includes(node.id)
    const digest = node.metadata?.digest
    const metadata = (node.metadata || {}) as Record<string, unknown>
    const discoveryMethods = Array.isArray(metadata.discovery_methods)
      ? metadata.discovery_methods.map(String)
      : []
    return {
      id: node.id,
      title: node.title,
      authors: node.authors.join(' · '),
      year: node.year ?? 0,
      citations: node.citation_count ?? node.citations ?? 0,
      similarity: isSeed ? 1 : 0,
      role: (isSeed ? 'seed' : node.role === 'prior' || node.role === 'derivative' ? node.role : 'related') as Paper['role'],
      x: isSeed ? 50 : 50 + Math.cos(angle) * 38,
      y: isSeed ? 48 : 48 + Math.sin(angle) * 38,
      abstract: digest?.plain_language_takeaway || node.abstract || '暂无摘要。',
      researchTopic: digest?.research_topic || '未提供研究主题',
      review: digest?.faithfulness_verdict === 'pass' ? 'pass' as const : 'review' as const,
      recommendation: Number(digest?.recommendation_score || 0),
      selectionScore: Number((node.metadata as Record<string, unknown> | undefined)?.selection_score || (node.metadata as Record<string, unknown> | undefined)?.ranking_score || 0),
      keywords: node.keywords || [],
      url: node.url,
      doi: node.doi || (typeof metadata.doi === 'string' ? metadata.doi : undefined),
      arxivId: node.arxiv_id || (typeof metadata.arxiv_id === 'string' ? metadata.arxiv_id : undefined),
      provider: typeof metadata.provider === 'string' ? metadata.provider : undefined,
      discoveryMethods,
      digest,
    }
  })
  const normalizedEdges = new Map<string, GraphResponse['edges'][number]>()
  graph.edges.forEach((edge) => {
    const isCitedBy = edge.relation === 'CITED_BY'
    const source = isCitedBy ? edge.target : edge.source
    const target = isCitedBy ? edge.source : edge.target
    const relation = isCitedBy ? 'CITES' : edge.relation
    const key = relation === 'CITES' ? `${source}|${target}|CITES` : `${source}|${target}|${relation}`
    if (!normalizedEdges.has(key)) normalizedEdges.set(key, { ...edge, source, target, relation })
  })
  const roleById = new Map(papers.map((paper) => [paper.id, paper.role]))
  const paperById = new Map(papers.map((paper) => [paper.id, paper]))
  const graphSeedIds = graph.seed_ids || [graph.seed]
  const priorEvidence = new Map<string, string[]>()
  const derivativeEvidence = new Map<string, string[]>()
  graph.edges.forEach((edge) => {
    if (edge.relation !== 'CITES' || edge.metadata?.synthetic === true || edge.metadata?.verified === false || edge.metadata?.direct === false) return
    const source = paperById.get(edge.source)
    const target = paperById.get(edge.target)
    if (!source || !target) return
    if (graphSeedIds.includes(target.id) && source.year > target.year) {
      derivativeEvidence.set(source.id, [...(derivativeEvidence.get(source.id) || []), target.id])
    }
    if (graphSeedIds.includes(source.id) && target.year < source.year) {
      priorEvidence.set(target.id, [...(priorEvidence.get(target.id) || []), source.id])
    }
  })
  papers.forEach((paper) => {
    if (graphSeedIds.includes(paper.id)) {
      paper.role = 'seed'
      return
    }
    const hasPrior = (priorEvidence.get(paper.id) || []).length > 0
    const hasDerivative = (derivativeEvidence.get(paper.id) || []).length > 0
    // A paper linked in both directions to different seeds is not safely
    // assignable to one side of the timeline.
    paper.role = hasPrior && hasDerivative ? 'related' : hasPrior ? 'prior' : hasDerivative ? 'derivative' : 'related'
  })
  const edges = [...normalizedEdges.values()].map((edge) => ({
    source: edge.source,
    target: edge.target,
    kind: edge.relation === 'AUTHOR_SHARED_BY' ? 'author' as const : edge.relation === 'CITES' && edge.metadata?.synthetic !== true ? 'citation' as const : 'similarity' as const,
    score: edge.weight ?? 0,
    relation: edge.relation,
    metadata: edge.metadata,
  }))
  return { papers, edges }
}

function mergeGraphs(base: GraphResponse, addition: GraphResponse): GraphResponse {
  const nodes = new Map(base.nodes.map((node) => [node.id, node]))
  addition.nodes.forEach((node) => {
    if (!nodes.has(node.id)) nodes.set(node.id, { ...node, is_seed: node.id === base.seed })
  })
  const edges = new Map(base.edges.map((edge) => [`${edge.source}|${edge.target}|${edge.relation}`, edge]))
  addition.edges.forEach((edge) => edges.set(`${edge.source}|${edge.target}|${edge.relation}`, edge))
  return {
    seed: base.seed,
    seed_ids: [...new Set([...(base.seed_ids || [base.seed]), ...(addition.seed_ids || [])])],
    multi_seed: (base.seed_ids || [base.seed]).length > 1 || (addition.seed_ids || []).length > 1,
    seed_title: base.seed_title,
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    stats: {
      node_count: nodes.size,
      citation_edge_count: [...edges.values()].filter((edge) => edge.relation === 'CITES' || edge.relation === 'CITATION_SIMILAR_TO').length,
      similarity_edge_count: [...edges.values()].filter((edge) => edge.relation === 'EMBEDDING_SIMILAR_TO').length,
    },
  }
}

function localGraphForLimit(data: { papers: Paper[]; edges: Edge[] }, paperId: string, limit: number): GraphResponse {
  const ordered = [...data.papers].sort((left, right) => {
    if (left.id === paperId) return -1
    if (right.id === paperId) return 1
    return right.selectionScore - left.selectionScore
  })
  const papers = ordered.slice(0, Math.min(limit, ordered.length))
  const ids = new Set(papers.map((paper) => paper.id))
  return {
    seed: paperId,
    seed_title: data.papers.find((paper) => paper.id === paperId)?.title || 'Seed map',
    nodes: papers.map((paper) => ({
      id: paper.id,
      title: paper.title,
      authors: paper.authors.split(' · '),
      year: paper.year,
      citation_count: paper.citations,
      global_impact: paper.citations,
      abstract: paper.abstract,
      is_seed: paper.id === paperId,
      seed_ids: paper.id === paperId ? [paperId] : [],
      role: paper.id === paperId ? 'seed' : paper.role,
      keywords: paper.keywords,
      url: paper.url,
      doi: paper.doi,
      arxiv_id: paper.arxivId,
      metadata: { provider: paper.provider, discovery_methods: paper.discoveryMethods },
    })),
    edges: data.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)).map((edge) => ({
      source: edge.source,
      target: edge.target,
      relation: edge.relation || (edge.kind === 'citation' ? 'CITATION_SIMILAR_TO' : edge.kind === 'author' ? 'AUTHOR_SHARED_BY' : 'EMBEDDING_SIMILAR_TO'),
      weight: edge.score,
      metadata: edge.metadata || (edge.kind === 'citation' ? { synthetic: true, source: 'demo' } : undefined),
    })),
    stats: { node_count: papers.length, citation_edge_count: data.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target) && edge.kind === 'citation').length, similarity_edge_count: data.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target) && edge.kind === 'similarity').length },
  }
}

const aiAnalysis: Record<string, AiAnalysis> = {
  seed: {
    tldr: '以日内高频收益构造 realized volatility，并将其作为可观测波动率指标用于测量、建模和预测。',
    contribution: '建立从高频数据、实现方差估计到波动率预测的统一研究框架，连接潜在波动率与可观测市场数据。',
    method: '聚合日内收益得到 realized variance，并结合时间序列模型、跳跃分解和多预测周期评估预测能力。',
    limitations: '结果依赖交易日内采样频率、市场微观结构噪声、跳跃识别规则和数据质量。',
    tags: ['Realized volatility', 'High frequency', 'Volatility forecasting'],
    question: '如何利用日内价格数据更准确地测量和预测资产的实际波动率？',
    evidence: '高频实现测度相较低频平方收益包含更多日内波动信息，但需要处理噪声和非同步交易。',
    dataset: '日内金融市场交易数据与日收益序列；具体市场和采样频率需结合原文确认。',
    ideas: [],
  },
  p1: {
    tldr: '系统比较多种机器学习方法在经验资产定价任务中的预测能力和经济价值。',
    contribution: '提供统一的模型比较基线，帮助区分统计预测提升与真正的投资收益提升。',
    method: '比较正则化、树模型和神经网络，并用滚动时间窗口进行样本外评估。',
    limitations: '模型排名可能随市场状态、特征集合和超参数选择而变化。',
    tags: ['Machine learning', 'Empirical finance', 'Benchmark'],
    question: '不同机器学习方法是否能稳定改善经验资产定价？',
    evidence: '统一基准实验比较了多类模型的样本外表现。',
    dataset: '历史公司特征与收益面板数据。',
    ideas: [],
  },
}

function getAiAnalysis(paper: Paper): AiAnalysis {
  if (paper.digest) {
    return {
      tldr: paper.digest.plain_language_takeaway || paper.digest.author_claim || '暂无通俗总结。',
      contribution: paper.digest.method || paper.digest.author_claim || '暂无结构化方法信息。',
      method: paper.digest.method || '暂无方法信息。',
      limitations: paper.digest.limitations || '暂无局限信息。',
      tags: [paper.digest.research_topic, paper.digest.analysis_agent].filter(Boolean) as string[],
      question: paper.digest.research_question || '暂无研究问题。',
      evidence: paper.digest.evidence_status || '暂无证据状态。',
      dataset: paper.digest.datasets || paper.digest.experiment_details || '暂无数据集信息。',
      ideas: (paper.digest.opinions || []).map((idea) => ({ title: String(idea.claim || ''), level: String(idea.confidence || ''), evidence: String(idea.supporting_evidence || '') })),
    }
  }
  return aiAnalysis[paper.id] ?? {
    tldr: `这篇论文围绕“${paper.title}”提出方法，并将其应用于金融研究中的预测或解释任务。`,
    contribution: '将新的建模方法与金融问题结合，为后续研究提供可复用的研究路径。',
    method: '通过数据驱动的模型训练与样本外实验，检验方法在真实研究场景中的有效性。',
    limitations: '当前摘要级解析未覆盖全部实验细节，结论仍需要结合原文和数据处理流程判断。',
    tags: ['Quantitative finance', 'Research method', 'Prediction'],
    question: '该论文试图解决什么金融研究问题？',
    evidence: '页面暂未提供结构化证据摘要。',
    dataset: '页面暂未提供数据集信息。',
    ideas: [],
  }
}

function DigestPanel({ paper, analysis }: { paper: Paper; analysis: AiAnalysis }) {
  const identifier = paper.arxivId || paper.doi || paper.id
  const link = paperLink(paper)
  return <aside className="details-panel panel digest-panel"><div className="detail-top"><span className={`role-badge ${paper.role}`}>{roleLabel[paper.role]}</span><span className={`review-badge ${paper.review}`}>{paper.review === 'pass' ? '审核通过' : '需复核'}</span></div><div className="detail-year">{paper.year || '年份未知'} <span>·</span> {paper.citations.toLocaleString()} citations</div><h2>{paper.title}</h2><p className="authors">{paper.authors || '作者信息未提供'}</p><div className="digest-meta"><span>{paper.researchTopic}</span><strong>{paper.recommendation ? `推荐 ${paper.recommendation.toFixed(1)}` : '推荐分数未提供'}</strong></div><div className="paper-identifiers"><span title={identifier}>{identifier}</span>{paper.provider && <span>来源：{paper.provider}</span>}</div>{paper.keywords.length > 0 && <div className="chips paper-keywords">{paper.keywords.map((keyword) => <span key={keyword}>{keyword}</span>)}</div>}<div className="detail-section"><label>摘要 / 页面摘要</label><p>{paper.abstract}</p></div><div className="detail-section"><label>研究问题</label><p>{analysis.question}</p></div><div className="detail-section"><label>方法与贡献</label><p>{analysis.contribution}</p></div><div className="detail-section"><label>证据状态</label><p>{analysis.evidence}</p></div><div className="detail-section"><label>数据集与实验</label><p>{analysis.dataset}</p></div><div className="detail-section"><label>局限</label><p>{analysis.limitations}</p></div><div className="chips ai-chips">{analysis.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>{paper.discoveryMethods.length > 0 && <small className="provenance-note">发现路径：{paper.discoveryMethods.join(' · ')}</small>}<div className="detail-section"><label>相关链接</label>{link && <a className="paper-link" href={link.href} target="_blank" rel="noreferrer" title={link.href}>↗ {link.href}</a>}</div></aside>
}

function App() {
  const [appMode, setAppMode] = useState<'forest' | 'paper'>('forest')
  const [forest, setForest] = useState<TopicForestData | null>(null)
  const [forestLoading, setForestLoading] = useState(true)
  const [selectedId, setSelectedId] = useState('seed')
  const [query, setQuery] = useState('')
  const [showCitations, setShowCitations] = useState(true)
  const [showSimilarity, setShowSimilarity] = useState(true)
  const [showAuthors, setShowAuthors] = useState(true)
  const [view, setView] = useState<'graph' | 'list'>('graph')
  const [workView, setWorkView] = useState<'overview' | 'prior' | 'derivative'>('overview')
  const [minSimilarity, setMinSimilarity] = useState(.55)
  const [apiGraph, setApiGraph] = useState<GraphResponse | null>(null)
  const [searchResults, setSearchResults] = useState<ApiPaper[]>([])
  const [apiMessage, setApiMessage] = useState('')
  const [detailTab, setDetailTab] = useState<'abstract' | 'ai'>('abstract')
  const [showFullAnalysis, setShowFullAnalysis] = useState(false)
  const [addingPaperId, setAddingPaperId] = useState<string | null>(null)
  const [expandingLimit, setExpandingLimit] = useState<number | null>(null)
  const [buildingSeedMap, setBuildingSeedMap] = useState(false)
  const [layoutMode, setLayoutMode] = useState<'force' | 'timeline'>('force')
  const [timelineFocusId, setTimelineFocusId] = useState<string | undefined>(undefined)
  const [seedIds, setSeedIds] = useState<string[]>(['seed'])
  const [maps, setMaps] = useState<ResearchMap[]>([])
  const [overlapIds, setOverlapIds] = useState<string[]>([])
  const [overlapResult, setOverlapResult] = useState<{ intersection: ApiPaper[]; bridge_papers: ApiPaper[]; gaps: string[] } | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [graphZoom, setGraphZoom] = useState(1)
  const [graphFocus, setGraphFocus] = useState(false)
  const graphPanelRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let cancelled = false
    fetch('/api/topic-forest').then((response) => {
      if (!response.ok) throw new Error('topic forest unavailable')
      return response.json() as Promise<TopicForestData>
    }).then((data) => {
      if (!cancelled) setForest(data)
    }).catch(() => {
      if (!cancelled) setApiMessage('主题森林暂时不可用，请确认后端已启动。')
    }).finally(() => {
      if (!cancelled) setForestLoading(false)
    })
    return () => { cancelled = true }
  }, [])
  const activeData = apiGraph ? graphToDemoShape(apiGraph) : { papers, edges }
  const viewPapers = activeData.papers.filter((paper) => workView === 'overview' || paper.role === 'seed' || paper.role === workView)
  const viewPaperIds = new Set(viewPapers.map((paper) => paper.id))
  const activeEdges = activeData.edges.filter((edge) => viewPaperIds.has(edge.source) && viewPaperIds.has(edge.target))
  const activePapers = useForceLayout(viewPapers, activeEdges)
  const selected = activePapers.find((paper) => paper.id === selectedId) ?? activePapers[0]
  const selectedAnalysis = getAiAnalysis(selected)
  const runSearch = async (value: string) => {
    setQuery(value)
    if (!value.trim()) { setSearchResults([]); return }
    try {
      setSearchResults((await searchPapers(value)).results)
      setSearchOpen(true)
      setApiMessage('')
    } catch {
      setSearchResults([])
      setSearchOpen(false)
      setApiMessage('搜索服务暂时不可用，请稍后重试。')
    }
  }
  const selectPaper = (paperId: string) => {
    setSelectedId(paperId)
    setDetailTab('abstract')
    setShowFullAnalysis(false)
    setSearchOpen(false)
  }
  const selectTimelinePaper = (paperId: string) => { setTimelineFocusId(paperId); selectPaper(paperId) }
  const findLocalForestGraph = (paperId: string): GraphResponse | null => {
    for (const root of forest?.roots || []) {
      for (const leaf of root.children) {
        for (const entry of leaf.graphs) {
          const graph = entry.graph as unknown as GraphResponse
          if (graph.nodes?.some((node) => node.id === paperId)) return graph
        }
      }
    }
    return null
  }
      const buildGraph = async (paperId: string) => {
        setSelectedId(paperId)
        setDetailTab('abstract')
        setShowFullAnalysis(false)
          setSearchOpen(false)
          setSearchResults([])
          try {
            const localGraph = findLocalForestGraph(paperId)
            if (localGraph) {
              setApiGraph(localGraph)
              setSeedIds(localGraph.seed_ids || [localGraph.seed])
              setSelectedId(paperId)
              setTimelineFocusId(undefined)
              setApiMessage(`已打开本地森林 graph：${localGraph.seed_ids?.length || 1} 个 seed。`)
              return
            }
            setApiGraph(await fetchGraph(paperId))
            setApiMessage('')
        } catch {
          setApiMessage('论文关联网络暂时不可用，当前图谱未切换；请稍后重试。')
        }
  }
  const addPaperToMap = async (paperId: string) => {
    setAddingPaperId(paperId)
    try {
      const addition = await fetchGraph(paperId)
      const current = apiGraph ?? {
        seed: 'seed', seed_title: papers[0].title, nodes: papers.map((paper) => ({ id: paper.id, title: paper.title, authors: paper.authors.split(' · '), year: paper.year, citation_count: paper.citations, global_impact: paper.citations, abstract: paper.abstract, is_seed: paper.role === 'seed', role: paper.role, metadata: {} })), edges: edges.map((edge) => ({ source: edge.source, target: edge.target, relation: edge.relation || (edge.kind === 'citation' ? 'CITATION_SIMILAR_TO' as const : edge.kind === 'author' ? 'AUTHOR_SHARED_BY' as const : 'EMBEDDING_SIMILAR_TO' as const), weight: edge.score, metadata: edge.metadata })), stats: { node_count: papers.length, citation_edge_count: 0, similarity_edge_count: 0 },
      }
      setApiGraph(mergeGraphs(current, addition))
      setSelectedId(paperId)
      setSearchOpen(false)
      setSearchResults([])
      setApiMessage(`已将“${addition.seed_title}”及其关联文献追加到当前图谱。`)
      setSearchResults((results) => results.filter((paper) => paper.id !== paperId))
    } catch {
      setApiMessage('追加论文失败，请检查 API 或论文 ID。')
    } finally {
      setAddingPaperId(null)
    }
  }
  const queuePaper = async (paper: ApiPaper) => {
    try {
      await queuePaperForParsing(paper, 'search_result')
      setApiMessage(`已将“${paper.title}”加入待解析队列。`)
    } catch {
      setApiMessage('加入解析队列失败，请检查 API。')
    }
  }
  const setAsSeed = (paperId: string) => {
    const alreadySeed = seedIds.includes(paperId)
    setSeedIds((current) => current.includes(paperId) ? current : [...current, paperId])
    setSelectedId(paperId)
    setTimelineFocusId(undefined)
    setApiMessage(alreadySeed ? '这篇论文已经在 Seed 列表中。点击 Build Seed Map 生成多 Seed 图谱。' : '已加入 Seed 列表。点击 Build Seed Map 生成多 Seed 图谱。')
  }
  const buildMultiSeedMap = async () => {
    if (!seedIds.length || buildingSeedMap) return
    setBuildingSeedMap(true)
    const localIds = new Set(activeData.papers.map((paper) => paper.id))
    try {
      const health = await fetchHealth()
      if (!health.ok) throw new Error('API health check failed')
      if (!apiGraph && seedIds.every((id) => localIds.has(id))) {
        const localGraph: GraphResponse = {
          seed: seedIds[0],
          seed_title: activeData.papers.find((paper) => paper.id === seedIds[0])?.title || 'Seed map',
          nodes: activeData.papers.map((paper) => ({ id: paper.id, title: paper.title, authors: paper.authors.split(' · '), year: paper.year, citation_count: paper.citations, global_impact: paper.citations, abstract: paper.abstract, is_seed: seedIds.includes(paper.id), seed_ids: seedIds.includes(paper.id) ? [paper.id] : [], role: seedIds.includes(paper.id) ? 'seed' : paper.role, metadata: {} })),
          edges: activeData.edges.map((edge) => ({ source: edge.source, target: edge.target, relation: edge.relation || (edge.kind === 'citation' ? 'CITATION_SIMILAR_TO' : edge.kind === 'author' ? 'AUTHOR_SHARED_BY' : 'EMBEDDING_SIMILAR_TO'), weight: edge.score, metadata: edge.metadata })),
          stats: { node_count: activeData.papers.length, citation_edge_count: activeData.edges.filter((edge) => edge.kind === 'citation').length, similarity_edge_count: activeData.edges.filter((edge) => edge.kind === 'similarity').length },
        }
        setApiGraph(localGraph)
        setTimelineFocusId(undefined)
        setSelectedId(seedIds[0])
        setApiMessage(`已用 ${seedIds.length} 个 Seed 生成本地图谱。`)
        return
      }
      setApiGraph(await buildSeedMap(seedIds))
      setTimelineFocusId(undefined)
      setSelectedId(seedIds[0] || selectedId)
      setApiMessage(`已用 ${seedIds.length} 篇 seed 重新生成图谱。`)
    } catch (error) {
      if (seedIds.every((id) => localIds.has(id))) {
        const localGraph: GraphResponse = {
          seed: seedIds[0],
          seed_title: activeData.papers.find((paper) => paper.id === seedIds[0])?.title || 'Seed map',
          nodes: activeData.papers.map((paper) => ({ id: paper.id, title: paper.title, authors: paper.authors.split(' · '), year: paper.year, citation_count: paper.citations, global_impact: paper.citations, abstract: paper.abstract, is_seed: seedIds.includes(paper.id), seed_ids: seedIds.includes(paper.id) ? [paper.id] : [], role: seedIds.includes(paper.id) ? 'seed' : paper.role, metadata: {} })),
          edges: activeData.edges.map((edge) => ({ source: edge.source, target: edge.target, relation: edge.relation || (edge.kind === 'citation' ? 'CITATION_SIMILAR_TO' : edge.kind === 'author' ? 'AUTHOR_SHARED_BY' : 'EMBEDDING_SIMILAR_TO'), weight: edge.score, metadata: edge.metadata })),
          stats: { node_count: activeData.papers.length, citation_edge_count: activeData.edges.filter((edge) => edge.kind === 'citation').length, similarity_edge_count: activeData.edges.filter((edge) => edge.kind === 'similarity').length },
        }
        setApiGraph(localGraph)
        setTimelineFocusId(undefined)
        setSelectedId(seedIds[0] || selectedId)
        setApiMessage(`已使用当前本地图谱构建 ${seedIds.length} 个 Seed；后端服务不可用，未重新获取外部论文。`)
      } else {
        const message = error instanceof Error ? error.message : 'unknown error'
        setApiMessage(`多 Seed 图谱生成失败：${message}。当前图谱保持不变。`)
      }
    } finally {
      setBuildingSeedMap(false)
    }
  }
  const expandSelectedGraph = async (limit: number) => {
    // The first-full-graph sample is a fixed seed-centered source. A node
    // selected inside the visualization must not change what 20/40/80 means.
    const isFirstFullGraph = apiGraph?.source === 'first_full_graph' || apiGraph?.seed === 'arxiv:1608.01795'
    const paperId = isFirstFullGraph ? 'arxiv:1608.01795' : timelineFocusId || selectedId
    if (!paperId) return
    setExpandingLimit(limit)
    try {
      const localGraph = localGraphForLimit(activeData, paperId, limit)
      if (localGraph.nodes.length > 0) {
        setApiGraph(localGraph)
        setSelectedId(paperId)
        setTimelineFocusId(undefined)
        setApiMessage(`已从本地数据加载 ${localGraph.nodes.length} 篇文献。`)
        return
      }
      const addition = isFirstFullGraph || paperId === 'seed' ? await fetchRealizedVolatilityGraph(limit) : await fetchGraph(paperId, limit)
      // The selected size is an explicit view size. Replacing the current
      // neighborhood (rather than merging it) makes 20/40/80 visibly
      // different and avoids an earlier 80-node graph masking a later 20.
      setApiGraph(addition)
      setSelectedId(addition.seed)
      setTimelineFocusId(undefined)
      setApiMessage(`已围绕当前论文加载 ${addition.nodes.length} 篇候选文献。`)
    } catch {
      const localPaper = activeData.papers.some((paper) => paper.id === paperId)
      if (localPaper) {
        const localGraph = localGraphForLimit(activeData, paperId, limit)
        setApiGraph(localGraph)
        setSelectedId(paperId)
        setTimelineFocusId(undefined)
        setApiMessage(`后端暂不可用，已在本地图谱中显示 ${localGraph.nodes.length} 篇文献。`)
      } else {
        setApiMessage('扩展论文失败，当前图谱保持不变。')
      }
    } finally {
      setExpandingLimit(null)
    }
  }
  const handleSearchAction = (action: 'select' | 'generate' | 'seed', paperId: string) => {
    if (action === 'select') selectPaper(paperId)
    if (action === 'generate') void buildGraph(paperId)
    if (action === 'seed') { selectPaper(paperId); setAsSeed(paperId); setApiMessage('论文已加入 Seed 列表，可点击 Build Seed Map。') }
  }
  const saveCurrentMap = async () => {
    if (!apiGraph) return setApiMessage('请先加载或构建一个图谱。')
    try { const saved = await saveMap({ title: selected.title, seed_ids: seedIds, graph: apiGraph }); setMaps((current) => [...current.filter((item) => item.id !== saved.id), saved]); setApiMessage('图谱已保存。') } catch { setApiMessage('保存图谱失败。') }
  }
  const loadSavedMap = (map: ResearchMap) => { setApiGraph(map.graph); setSeedIds(map.seed_ids); setSelectedId(map.graph.seed); setApiMessage(`已加载图谱：${map.title}`) }
  const refreshMaps = async () => { try { setMaps((await listMaps()).results) } catch { setApiMessage('无法加载已保存图谱。') } }
  const exportCurrentMap = (format: 'json' | 'csv') => {
    if (!apiGraph) return
    const content = format === 'json' ? JSON.stringify(apiGraph, null, 2) : ['id,title,year,citations', ...apiGraph.nodes.map((node) => `${JSON.stringify(node.id)},${JSON.stringify(node.title)},${node.year ?? ''},${node.citation_count ?? 0}`)].join('\n')
    const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([content], { type: format === 'json' ? 'application/json' : 'text/csv' })); link.download = `paper-graph.${format}`; link.click(); URL.revokeObjectURL(link.href)
  }
  const calculateOverlap = async () => { if (overlapIds.length < 2) return; try { setOverlapResult(await overlapMaps(overlapIds)); setApiMessage('图谱交集分析完成。') } catch { setApiMessage('图谱交集分析失败。') } }
  const startNewGraph = () => {
    setApiGraph(null)
    setAppMode('forest')
    setSelectedId('seed')
    setQuery('')
    setSearchResults([])
    setSearchOpen(false)
    setApiMessage('')
    setDetailTab('abstract')
    setShowFullAnalysis(false)
    setView('graph')
    setGraphZoom(1)
    setGraphFocus(false)
    setAddingPaperId(null)
  }
  const shareGraph = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setApiMessage('图谱链接已复制。')
    } catch {
      setApiMessage('当前浏览器不允许自动复制，请手动复制地址栏链接。')
    }
  }
  const toggleGraphFocus = async () => {
    if (!document.fullscreenElement && graphPanelRef.current) {
      await graphPanelRef.current.requestFullscreen?.()
      setGraphFocus(true)
    } else if (document.exitFullscreen) {
      await document.exitFullscreen()
      setGraphFocus(false)
    }
  }
  const openForestGraph = async (entry: { graph: Record<string, unknown>; graph_id: string }, leaf: { label: string }) => {
    const graph = entry.graph as unknown as GraphResponse
    try {
      const lookup = await fetchArxivAvailability(graph.nodes.map((node) => node.id))
      const byId = new Map(lookup.results.map((item) => [item.paper_id, item]))
      const enriched: GraphResponse = {
        ...graph,
        nodes: graph.nodes.map((node) => {
          const arxiv = byId.get(node.id)
          if (!arxiv?.arxiv_id) return node
          return { ...node, arxiv_id: arxiv.arxiv_id, metadata: { ...(node.metadata || {}), arxiv_id: arxiv.arxiv_id, arxiv_url: arxiv.arxiv_url, arxiv_pdf_url: arxiv.arxiv_pdf_url, arxiv_status: arxiv.status } }
        }),
      }
      setApiGraph(enriched)
      const linked = lookup.results.filter((item) => item.status === 'linked').length
      setApiMessage(`已打开 ${leaf.label} · ${entry.graph_id}；OpenAlex 找到 ${linked}/${lookup.queried} 篇 arXiv 关联`)
    } catch {
      setApiGraph(graph)
      setApiMessage(`已打开 ${leaf.label} · ${entry.graph_id}；arXiv 查询暂时失败`)
    }
    setSeedIds(graph.seed_ids || [graph.seed])
    setSelectedId(graph.seed)
    setTimelineFocusId(undefined)
    setAppMode('paper')
  }
  const filtered = useMemo(() => activePapers.filter((paper) => !query || `${paper.title} ${paper.authors} ${paper.researchTopic}`.toLowerCase().includes(query.toLowerCase())), [activePapers, query])
  const visibleEdges = activeEdges.filter((edge) => edge.kind === 'author' ? showAuthors : (edge.kind === 'citation' ? showCitations : showSimilarity) && (edge.kind !== 'similarity' || edge.score >= minSimilarity))
  const seedIdSet = new Set(activePapers.filter((paper) => paper.role === 'seed').map((paper) => paper.id))
  const seedEdges = visibleEdges.filter((edge) => seedIdSet.has(edge.source) || seedIdSet.has(edge.target))
  const otherEdges = visibleEdges.filter((edge) => !seedIdSet.has(edge.source) && !seedIdSet.has(edge.target))
  const rankEdges = (edgesToRank: Edge[]) => [...edgesToRank].sort((left, right) => {
    const leftCitation = left.relation === 'CITES' ? 1 : 0
    const rightCitation = right.relation === 'CITES' ? 1 : 0
    return rightCitation - leftCitation || right.score - left.score
  })
  // The generated map is seed-centered: do not render relations between two
  // non-seed papers in the primary network view. They add visual noise and
  // make prior/derivative direction look like a global graph claim.
  const graphEdges = rankEdges(seedEdges).slice(0, 120)
  const radius = (citations: number) => 7 + Math.sqrt(Math.max(citations, 0) / 4820) * 17
  const yearColor = (_year: number, selected: boolean) => selected ? '#3f8056' : '#68aa78'
  const yearOpacity = (year: number) => .24 + (Math.min(Math.max(year - 1992, 0), 34) / 34) * .62
  const paperById = new Map(activePapers.map((paper) => [paper.id, paper]))

  useEffect(() => {
    const closeSearchOnOutsideClick = (event: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(event.target as Node)) setSearchOpen(false)
    }
    document.addEventListener('mousedown', closeSearchOnOutsideClick)
    return () => document.removeEventListener('mousedown', closeSearchOnOutsideClick)
  }, [])

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><span className="brand-mark">✦</span><span>paper<span className="brand-accent">graph</span></span></div>
      <SearchBar value={query} results={searchResults} onChange={runSearch} onAction={handleSearchAction} onAdd={addPaperToMap} onQueue={queuePaper} />
      <nav><button onClick={() => { if (appMode === 'forest') { if (apiGraph) setAppMode('paper'); else setApiMessage('请先从主题森林打开一个已实现的本地图谱。') } else setAppMode('forest') }}>{appMode === 'forest' ? 'Paper graph' : 'Forest'}</button><button onClick={() => setApiMessage('使用搜索框输入论文标题、作者、DOI 或 arXiv ID。')}>Docs</button><button onClick={shareGraph}>Share</button><button className="avatar" onClick={() => setApiMessage('当前为本地研究图谱。')}>ZG</button></nav>
    </header>

    <main>{apiMessage && <div className="api-notice">{apiMessage}</div>}
      {appMode === 'forest' ? (forestLoading ? <div className="forest-loading panel">正在读取主题森林…</div> : forest ? <TopicForest data={forest} onOpenGraph={openForestGraph} /> : <div className="forest-loading panel">主题森林加载失败。</div>) : <>
      <section className="graph-header">
        <div><div className="eyebrow">SEED-CENTERED RESEARCH MAP <span className="seed-count">· {seedIds.length} SEEDS</span></div><h1>{selected.title}</h1>{paperLink(selected) && <a className="paper-link header-paper-link" href={paperLink(selected)!.href} target="_blank" rel="noreferrer" title={paperLink(selected)!.href}>↗ {paperLink(selected)!.href}</a>}<p>{selected.authors || '作者信息未提供'} <span className="dot">·</span> {selected.year || '年份未知'}</p><div className="seed-strip">{seedIds.map((id) => { const seed = activeData.papers.find((paper) => paper.id === id); return <button type="button" key={id} className={selectedId === id ? 'active' : ''} title={seed?.title || id} onClick={() => selectPaper(id)}>{seed?.title || id}</button> })}</div></div>
        <div className="header-actions"><button className="ghost" onClick={() => setView(view === 'graph' ? 'list' : 'graph')}>{view === 'graph' ? '☷ List view' : '◉ Graph view'}</button><button className="ghost" onClick={() => setLayoutMode(layoutMode === 'force' ? 'timeline' : 'force')}>{layoutMode === 'force' ? 'Timeline view' : 'Network view'}</button><button className="primary" onClick={startNewGraph}>＋ New graph</button></div>
      </section>

      <section className="workspace">
        <aside className="control-panel panel">
          <div className="panel-heading"><span>Graph controls</span><span className="settings">⚙</span></div>
          <div className="control-group"><label>RELATION LAYERS</label><button className={`layer-toggle ${showSimilarity ? 'active similarity' : ''}`} onClick={() => setShowSimilarity(!showSimilarity)}><span className="line-swatch similarity-line" />Similarity <span className="toggle">{showSimilarity ? 'ON' : 'OFF'}</span></button><button className={`layer-toggle ${showCitations ? 'active citations' : ''}`} onClick={() => setShowCitations(!showCitations)}><span className="line-swatch citation-line" />Citations <span className="toggle">{showCitations ? 'ON' : 'OFF'}</span></button><button className={`layer-toggle ${showAuthors ? 'active authors' : ''}`} onClick={() => setShowAuthors(!showAuthors)}><span className="line-swatch author-line" />Authors <span className="toggle">{showAuthors ? 'ON' : 'OFF'}</span></button></div>
          <div className="control-group"><label>MINIMUM SIMILARITY <strong>{minSimilarity.toFixed(2)}</strong></label><input className="range" type="range" min=".4" max=".9" step=".01" value={minSimilarity} onChange={(event) => setMinSimilarity(Number(event.target.value))} /></div>
          <div className="control-group"><label>VIEWS</label><button className={`mode ${workView === 'overview' ? 'active' : ''}`} onClick={() => setWorkView('overview')}>◎ Overview <span className="view-count">{activeData.papers.length}</span></button><button className={`mode ${workView === 'prior' ? 'active' : ''}`} onClick={() => setWorkView('prior')}>↗ Prior works <span className="view-count">{activeData.papers.filter((paper) => paper.role === 'prior').length}</span></button><button className={`mode ${workView === 'derivative' ? 'active' : ''}`} onClick={() => setWorkView('derivative')}>↘ Derivative works <span className="view-count">{activeData.papers.filter((paper) => paper.role === 'derivative').length}</span></button><small className="view-breakdown">{activeData.papers.filter((paper) => paper.role === 'seed').length} seed · {activeData.papers.filter((paper) => paper.role === 'prior').length} prior · {activeData.papers.filter((paper) => paper.role === 'derivative').length} derivative · {activeData.papers.filter((paper) => paper.role === 'related').length} related = {activeData.papers.length} total</small></div>
          <div className="control-group"><label>SEED MAP</label><SeedSelector selected={seedIds} onBuild={() => { void buildMultiSeedMap() }} building={buildingSeedMap} /><button className="mode" onClick={() => setSeedIds([])}>Clear seeds</button></div>
          <div className="control-group"><label>DISCOVERY</label><div className="expand-actions"><span>Expand around selected</span><div><button type="button" disabled={expandingLimit !== null} onClick={() => { void expandSelectedGraph(20) }}>20</button><button type="button" disabled={expandingLimit !== null} onClick={() => { void expandSelectedGraph(40) }}>40</button><button type="button" disabled={expandingLimit !== null} onClick={() => { void expandSelectedGraph(80) }}>80</button></div>{expandingLimit !== null && <small>Loading {expandingLimit} papers…</small>}</div></div>
          <div className="control-group"><label>MAPS</label><button className="mode" onClick={saveCurrentMap}>Save current map</button><button className="mode" onClick={() => { void refreshMaps() }}>Load saved maps</button><button className="mode" onClick={() => exportCurrentMap('json')}>Export JSON</button><button className="mode" onClick={() => exportCurrentMap('csv')}>Export CSV</button><MapSelector maps={maps} onLoad={loadSavedMap} onDelete={(id) => { void deleteMap(id).then(refreshMaps) }} onCopy={(id) => { void copyMap(id).then(refreshMaps) }} /></div>
          <div className="control-group"><label>MAP OVERLAP</label>{maps.map((map) => <label key={map.id}><input type="checkbox" checked={overlapIds.includes(map.id)} onChange={() => setOverlapIds((current) => current.includes(map.id) ? current.filter((id) => id !== map.id) : [...current, map.id])} /> {map.title}</label>)}<button className="mode" onClick={() => { void calculateOverlap() }}>Analyze overlap</button>{overlapResult && <><OverlapLegend intersectionCount={overlapResult.intersection.length} bridgeCount={overlapResult.bridge_papers.length} /><small>{overlapResult.gaps.join(' · ')}</small></>}</div>
          <div className="control-group legend"><label>VISUAL ENCODING</label><div><span className="legend-node impact" /> <span>Global impact · node size</span></div><div><span className="legend-gradient" /> <span>Publication year · node opacity</span></div><div><span className="line-swatch similarity-line" /> <span>Similarity · solid blue</span></div><div><span className="line-swatch citation-line" /> <span>Citations · red arrow</span></div><div><span className="line-swatch author-line" /> <span>Authors · purple dashed</span></div></div>
        </aside>

        {view === 'graph' ? <div ref={graphPanelRef} className={`graph-panel panel ${graphFocus ? 'graph-focus' : ''}`}>{layoutMode === 'force' && <GraphToolbar papers={activePapers.length} connections={graphEdges.length} zoomIn={() => setGraphZoom((zoom) => Math.min(2.4, zoom * 1.15))} zoomOut={() => setGraphZoom((zoom) => Math.max(.7, zoom / 1.15))} fullscreen={toggleGraphFocus} />}{layoutMode === 'timeline' ? <TimelineGraph papers={activePapers} edges={visibleEdges} seedIds={seedIds} selectedId={timelineFocusId} onSelect={selectTimelinePaper} onClearSelection={() => setTimelineFocusId(undefined)} /> : <ForceGraph papers={activePapers} edges={graphEdges} selectedId={selectedId} onSelect={selectPaper} onGenerate={(id) => { void buildGraph(id) }} onSeed={setAsSeed} onAdd={(id) => { void addPaperToMap(id) }} />}<div className="map-status"><span className="live-dot" /> {layoutMode === 'force' ? 'Layout stabilized' : 'Timeline'} <span>·</span> {workView === 'overview' ? 'Overview' : workView === 'prior' ? 'Prior works' : 'Derivative works'} · {activePapers.length} papers</div></div> : <div className="list-panel panel">{filtered.filter((paper) => workView === 'overview' || paper.role === 'seed' || paper.role === workView).map((paper) => <button className={`paper-row ${selectedId === paper.id ? 'selected-row' : ''}`} key={paper.id} onClick={() => selectPaper(paper.id)}><span className="row-rank">{roleLabel[paper.role]}</span><span className="row-title">{paper.title}<small>{paper.authors} · {paper.year}</small></span><span className="row-metric">{paper.citations.toLocaleString()}<small>citations</small></span><span className="row-metric accent-text">{paper.similarity.toFixed(2)}<small>similarity</small></span></button>)}</div>}

        <DigestPanel paper={selected} analysis={selectedAnalysis} /><PaperDetails paper={selected} onSetSeed={setAsSeed} onGenerate={(id) => { void buildGraph(id) }} onAdd={(id) => { void addPaperToMap(id) }} />
      </section>
      </>}
    </main>
    <footer><span>Paper Graph <b>·</b> Local research intelligence</span><span>Data is illustrative · Similarity and citation layers are independently rendered</span></footer>
  </div>
}

export default App
