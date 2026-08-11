import type { ApiPaper } from '../lib/api'

type SearchBarProps = {
	value: string
	results: ApiPaper[]
	onChange: (value: string) => void
	onAction: (action: 'select' | 'generate' | 'seed', id: string) => void
	onAdd: (id: string) => void
	onQueue: (paper: ApiPaper) => void
}

export function SearchBar({ value, results, onChange, onAction, onAdd, onQueue }: SearchBarProps) {
	const clearSearch = () => onChange('')

	return <div className="global-search">
		<span aria-hidden="true">⌕</span>
		<input value={value} onChange={(event) => onChange(event.target.value)} placeholder="Search papers, authors, DOI or arXiv ID…" aria-label="Search papers, authors, DOI or arXiv ID" />
		{value && <button type="button" className="clear-search" onClick={clearSearch} aria-label="取消搜索" title="取消搜索">×</button>}
		<kbd>⌘ K</kbd>
		{results.length > 0 && <div className="search-results"><div className="search-results-header"><span>普通搜索 · {results.length} 篇结果</span><small>Crossref · Semantic Scholar · OpenAlex</small></div>{results.map((paper) => <div className="search-result" key={paper.id}><button type="button" className="search-result-main" onClick={() => onAction('select', paper.id)}><strong>{paper.title}</strong><small>{paper.metadata?.provider ?? 'local'} · {paper.id} · {paper.year ?? '—'}</small></button><div className="search-result-actions"><button type="button" onClick={() => onAction('generate', paper.id)}>Graph</button><button type="button" onClick={() => onAction('seed', paper.id)}>Seed list</button><button type="button" className="add-to-map" title="将论文及其关联文献追加到当前图谱" onClick={() => onAdd(paper.id)}>+ Current map</button><button type="button" onClick={() => onQueue(paper)}>Queue parse</button></div></div>)}</div>}
	</div>
}
