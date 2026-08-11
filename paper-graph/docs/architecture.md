# Architecture

## Scope

Paper Graph is a local-first graph pipeline for quantitative-finance papers.
The first graph version has exactly two paper-to-paper edge types.

## Planned layers

1. **Identity layer**：将 arXiv、DOI、OpenAlex 和 Semantic Scholar ID 归并为 canonical paper ID。
2. **Metadata layer**：保存标题、作者、年份、摘要和来源。
3. **Graph layer**：只保存两类关系：`CITATION_SIMILAR_TO` 和 `EMBEDDING_SIMILAR_TO`。
4. **Similarity layer**：保存 embedding similarity 及每篇论文的 Top-K 邻居；这一层只用于计算相似关系和局部网络排序。
5. **Evidence layer**：从全文抽取方法、数据集、发现、限制和量化交易信号。
6. **Query layer**：支持主题检索、研究脉络、相似论文和证据回溯。

## Embedding text policy

The primary embedding uses title plus normalized author keywords. The abstract
is auxiliary and truncated before embedding. This makes the main graph more
topic-focused while retaining a second text variant for validation. A missing
abstract does not invalidate a paper; a missing keyword list lowers its text
quality level and falls back to title plus truncated abstract.

## Edge contract

### CITATION_SIMILAR_TO

- Undirected in meaning; endpoints are stored in stable order.
- Combines bibliographic coupling and co-citation.
- `weight` is the normalized combined score.
- Metadata retains both component scores and their weights.

### EMBEDDING_SIMILAR_TO

- Undirected in meaning; storage uses a stable sorted endpoint order.
- `weight` stores cosine similarity.
- Metadata should record the embedding model, metric, and candidate set.
- It must not be interpreted as a citation.

## Connected Papers-inspired local graph

The system does not attempt to reproduce a proprietary product. It adopts the
general, verifiable workflow: start from seed papers, collect a bounded local
candidate set using references and cited-by sets, calculate co-citation and
bibliographic coupling, rank local neighbours, and retain provenance.

第一阶段只实现本地模型和文件格式；接入外部 API 前必须先增加缓存、预算、断点和小规模测试。
