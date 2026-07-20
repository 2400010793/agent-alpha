# Paper Crawler Handoff

This project intentionally does not implement paper crawling in the first code skeleton.

Give this instruction to the separate crawler AI:

```text
You are responsible only for paper/document acquisition and reading-note preparation for Agent Alpha.

Inputs:
- Paper source configuration, such as arXiv/RSS/web/local PDF lists.
- Existing crawler references from my-paper-digest-new2.

Outputs required by Agent Alpha:
- data/raw_papers/: original PDF/HTML/metadata when available.
- data/parsed_papers/: cleaned Markdown/text with section boundaries.
- data/reading_notes/*.json: reading_note_v1 records.
- data/document_chunks/*.jsonl: evidence chunks with doc_id, chunk_id, source, title, page/section, text, created_at.

Hard requirements:
- Do not generate factors.
- Do not evaluate factors.
- Do not put API keys in files.
- Every reading note must preserve source ids and evidence ids.
- If a paper does not disclose sample, formula, data, cost, or out-of-sample evidence, write "输入未披露" instead of inventing it.

Agent Alpha will consume only the produced reading_note_v1 and document_chunks files.
```