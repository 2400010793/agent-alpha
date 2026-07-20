from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_alpha.config import project_path


@dataclass(frozen=True)
class EvidenceChunk:
    doc_id: str
    chunk_id: str
    source_type: str
    source_format: str
    source_url: str
    title: str
    authors: list[str]
    published_at: str
    section: str
    page: int | None
    text: str
    license: str
    created_at: str
    formula_blocks: list[str] = field(default_factory=list)
    table_captions: list[str] = field(default_factory=list)
    figure_captions: list[str] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？.!?])\s+|\n{2,}", text)
    return [part.strip() for part in parts if part.strip()]


def chunk_parsed_paper(parsed_path: str | Path, output_dir: str | Path = "data/document_chunks", max_chars: int = 1800) -> list[EvidenceChunk]:
    parsed = json.loads(Path(parsed_path).read_text(encoding="utf-8"))
    chunks: list[EvidenceChunk] = []
    created_at = _now_iso()
    for section in parsed.get("sections", []):
        buffer: list[str] = []
        buffer_len = 0
        for sentence in _sentences(str(section.get("text", ""))):
            if buffer and buffer_len + len(sentence) > max_chars:
                chunk_index = len(chunks) + 1
                chunk_text = "\n".join(buffer).strip()
                chunks.append(_build_chunk(parsed, section, chunk_index, chunk_text, created_at))
                buffer = []
                buffer_len = 0
            buffer.append(sentence)
            buffer_len += len(sentence)
        if buffer:
            chunk_index = len(chunks) + 1
            chunks.append(_build_chunk(parsed, section, chunk_index, "\n".join(buffer).strip(), created_at))
    out_dir = project_path(str(output_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{parsed['doc_id']}.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    return chunks


def _build_chunk(parsed: dict[str, Any], section: dict[str, Any], chunk_index: int, text: str, created_at: str) -> EvidenceChunk:
    doc_id = str(parsed["doc_id"])
    return EvidenceChunk(
        doc_id=doc_id,
        chunk_id=f"{doc_id}::chunk_{chunk_index:04d}",
        source_type=str(parsed.get("source_type", "")),
        source_format=str(section.get("source_format") or parsed.get("source_format", "")),
        source_url=str(parsed.get("source_url", "")),
        title=str(parsed.get("title", "")),
        authors=list(parsed.get("authors", [])),
        published_at=str(parsed.get("published_at", "")),
        section=str(section.get("section", "")),
        page=section.get("page"),
        text=text,
        formula_blocks=list(section.get("formula_blocks", [])),
        table_captions=list(section.get("table_captions", [])),
        figure_captions=list(section.get("figure_captions", [])),
        license=str(parsed.get("license", "")),
        created_at=created_at,
    )


def chunks_to_dicts(chunks: list[EvidenceChunk]) -> list[dict[str, Any]]:
    return [asdict(chunk) for chunk in chunks]