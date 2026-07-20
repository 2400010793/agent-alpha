from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from agent_alpha.config import project_path
from agent_alpha.memory.document_ingestor import chunk_parsed_paper
from agent_alpha.paper.paper_fetcher import fetch_local_path
from agent_alpha.paper.paper_parser import parse_raw_paper
from agent_alpha.paper.source_loader import PaperSource, load_paper_sources
from agent_alpha.reading.evidence_extractor import build_rma_records
from agent_alpha.reading.extractive_paper_reader import build_extractive_reading_note


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest one local research document into Agent Alpha paper memory artifacts.")
    parser.add_argument("path", help="Local Markdown, text, HTML, or PDF file.")
    parser.add_argument("--source-id", default="local_manual", help="Source id to record in metadata.")
    parser.add_argument("--source-type", default="local_document", help="Source type to record in metadata.")
    parser.add_argument("--config", default="configs/paper_sources.yaml", help="Paper source config path, used for default output settings.")
    return parser


def ingest_local_document(path: str | Path, *, source_id: str = "local_manual", source_type: str = "local_document", config_path: str | Path = "configs/paper_sources.yaml") -> dict[str, object]:
    source_config = load_paper_sources(config_path)
    output_dir = str(source_config.defaults.get("output_dir", "data/raw_papers"))
    source = PaperSource(id=source_id, type="local", source_type=source_type, source_name=source_id)
    raw_record = fetch_local_path(path, source, output_dir=output_dir)
    parsed = parse_raw_paper(raw_record.metadata_path)
    chunks = chunk_parsed_paper(parsed.parsed_path)
    note = build_extractive_reading_note(chunks)
    rma_records = build_rma_records(chunks)
    rma_dir = project_path("data/rma_records")
    rma_dir.mkdir(parents=True, exist_ok=True)
    rma_path = rma_dir / f"{raw_record.paper_id}.jsonl"
    with rma_path.open("w", encoding="utf-8") as handle:
        for record in rma_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {
        "paper_id": raw_record.paper_id,
        "raw_metadata": raw_record.metadata_path,
        "parsed_paper": parsed.parsed_path,
        "document_chunks": f"data/document_chunks/{raw_record.paper_id}.jsonl",
        "reading_note": f"data/reading_notes/{raw_record.paper_id}.json",
        "rma_records": str(rma_path),
        "chunk_count": len(chunks),
        "rma_keep_count": sum(1 for record in rma_records if record["decision"] == "KEEP"),
        "reading_note_schema": note["schema_version"],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = ingest_local_document(args.path, source_id=args.source_id, source_type=args.source_type, config_path=args.config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())