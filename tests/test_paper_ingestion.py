from __future__ import annotations

import json
from pathlib import Path
import shutil
import tarfile

from agent_alpha.config import project_path
from agent_alpha.paper.paper_fetcher import fetch_source
from agent_alpha.paper.relevance_filter import FetchFilterConfig, evaluate_fetch_gate
from agent_alpha.paper.source_loader import PaperSource
from agent_alpha.paper.source_loader import load_paper_sources
from agent_alpha.reading.note_schema import validate_reading_note
from agent_alpha.signals.reading_gate import ReadingGateConfig, evaluate_reading_gate
from agent_alpha.workflows.ingest_local_paper import ingest_local_document


def test_load_paper_sources_and_fetch_local_pattern(tmp_path: Path) -> None:
    sample = tmp_path / "source_doc.md"
    sample.write_text("# Source Doc\n\nHigh-frequency spread and volume note.", encoding="utf-8")
    config_path = tmp_path / "paper_sources.yaml"
    config_path.write_text(
        f"""schema_version: paper_sources_v1
defaults:
  output_dir: {tmp_path / "raw"}
sources:
  - id: tmp_local
    type: local
    enabled: true
    paths:
      - {sample}
    source_type: local_document
""",
        encoding="utf-8",
    )

    config = load_paper_sources(config_path)
    assert config.enabled_sources[0].id == "tmp_local"
    records = fetch_source(config.enabled_sources[0], output_dir=tmp_path / "raw")
    assert len(records) == 1
    assert Path(records[0].metadata_path).exists()


def test_fetch_source_filters_rss_entries_before_raw_write(tmp_path: Path) -> None:
        rss = tmp_path / "feed.xml"
        rss.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<rss><channel>
    <item>
        <title>Limit order book imbalance and intraday liquidity</title>
        <link>https://example.test/lob</link>
        <description>High-frequency spread, volume, and order book microstructure.</description>
    </item>
    <item>
        <title>Annual report fundamentals and analyst forecasts</title>
        <link>https://example.test/fundamental</link>
        <description>Revenue and earnings discussion only.</description>
    </item>
</channel></rss>
""",
                encoding="utf-8",
        )
        source = PaperSource(id="tmp_rss", type="rss", url=rss.as_uri(), source_type="paper")
        filter_config = FetchFilterConfig(max_age_days=0, download_full_text=False)

        records = fetch_source(source, output_dir=tmp_path / "raw", fetch_filter=filter_config)

        assert len(records) == 1
        payload = json.loads(Path(records[0].raw_path).read_text(encoding="utf-8"))
        assert payload["source_url"] == "https://example.test/lob"
        assert payload["fetch_gate"]["should_fetch"] is True
        drop_gate = evaluate_fetch_gate(
                {"title": "Annual report fundamentals", "abstract": "Revenue and earnings", "source_type": "paper"},
                filter_config,
        )
        assert drop_gate.should_fetch is False


def test_ingest_local_markdown_generates_agent_alpha_artifacts(tmp_path: Path) -> None:
    sample = tmp_path / "lob_imbalance_note.md"
    sample.write_text(
        """# Limit Order Book Imbalance\n\n"
        "This paper studies whether high-frequency limit order book imbalance predicts intraday returns.\n\n"
        "## Data\n\n"
        "The dataset uses tick data, bid and ask prices, bid and ask depth, spread, volume, and turnover.\n\n"
        "## Mechanism\n\n"
        "Order imbalance can reflect liquidity pressure because aggressive buying consumes ask depth and may move close prices.\n\n"
        "## Formula\n\n"
        "Imbalance = (bidV1 - askV1) / (bidV1 + askV1).\n\n"
        "## Limitation\n\n"
        "News and analyst recommendations are not available to Agent Alpha formulas and should remain context only.\n"
        """,
        encoding="utf-8",
    )

    result = ingest_local_document(sample)

    try:
        raw_metadata = Path(str(result["raw_metadata"]))
        assert raw_metadata.exists()
        assert project_path("data/parsed_papers", f"{result['paper_id']}.json").exists()
        chunks_path = project_path("data/document_chunks", f"{result['paper_id']}.jsonl")
        note_path = project_path("data/reading_notes", f"{result['paper_id']}.json")
        rma_path = project_path("data/rma_records", f"{result['paper_id']}.jsonl")
        assert chunks_path.exists()
        assert note_path.exists()
        assert rma_path.exists()

        note = json.loads(note_path.read_text(encoding="utf-8"))
        validate_reading_note(note)
        assert note["schema_version"] == "reading_note_v1"
        assert note["supporting_evidence"]
        assert note["score_dimensions"]
        assert note["recommendation_score"] >= 5.5
        gate = evaluate_reading_gate(note, ReadingGateConfig())
        assert gate.should_continue is True

        rma_records = [json.loads(line) for line in rma_path.read_text(encoding="utf-8").splitlines()]
        assert any(record["decision"] == "KEEP" for record in rma_records)
        assert all("ret30s" not in record["available_proxy_fields"] for record in rma_records)
    finally:
        shutil.rmtree(project_path("data/raw_papers", str(result["paper_id"])), ignore_errors=True)
        for relative_path in (
            project_path("data/parsed_papers", f"{result['paper_id']}.json"),
            project_path("data/document_chunks", f"{result['paper_id']}.jsonl"),
            project_path("data/reading_notes", f"{result['paper_id']}.json"),
            project_path("data/rma_records", f"{result['paper_id']}.jsonl"),
        ):
            relative_path.unlink(missing_ok=True)


def test_ingest_local_latex_uses_unified_chunk_interface(tmp_path: Path) -> None:
    sample = tmp_path / "lob_imbalance.tex"
    sample.write_text(
        r"""
\begin{abstract}
This paper studies high-frequency limit order book imbalance and intraday liquidity.
\end{abstract}
\section{Mechanism}
Order imbalance can predict short-horizon return because bid depth and ask depth proxy liquidity pressure.
\begin{equation}
I_t = \frac{bidV1_t - askV1_t}{bidV1_t + askV1_t}
\end{equation}
\section{Data}
The sample uses tick data, spread, volume, bid prices, ask prices, and top-book depth.
""",
        encoding="utf-8",
    )

    result = ingest_local_document(sample)

    try:
        parsed_path = project_path("data/parsed_papers", f"{result['paper_id']}.json")
        chunks_path = project_path("data/document_chunks", f"{result['paper_id']}.jsonl")
        note_path = project_path("data/reading_notes", f"{result['paper_id']}.json")
        parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
        chunks = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]
        note = json.loads(note_path.read_text(encoding="utf-8"))

        assert parsed["source_format"] == "latex"
        assert any(section["formula_blocks"] for section in parsed["sections"])
        assert all(chunk["source_format"] == "latex" for chunk in chunks)
        assert any(chunk["formula_blocks"] for chunk in chunks)
        assert any("bidV1" in formula for formula in note["core_formulas"])
    finally:
        shutil.rmtree(project_path("data/raw_papers", str(result["paper_id"])), ignore_errors=True)
        for relative_path in (
            project_path("data/parsed_papers", f"{result['paper_id']}.json"),
            project_path("data/document_chunks", f"{result['paper_id']}.jsonl"),
            project_path("data/reading_notes", f"{result['paper_id']}.json"),
            project_path("data/rma_records", f"{result['paper_id']}.jsonl"),
        ):
            relative_path.unlink(missing_ok=True)


def test_ingest_local_arxiv_source_tar_parses_latex_sections(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    tex = source_dir / "paper.tex"
    tex.write_text(
        r"""
\begin{abstract}
High-frequency trading synchronizes prices in fragmented financial markets.
\end{abstract}
\section{Introduction}
The paper studies price synchronization and high-frequency arbitrage.
\section{Model}
\begin{equation}
p_t = m_t + e_t
\end{equation}
where p_t is the observed price and m_t is a reference price.
\section{Empirical Results}
The data sample and empirical results are discussed.
\section{Conclusion}
Limitations and costs are not fully disclosed.
""",
        encoding="utf-8",
    )
    archive = tmp_path / "paper_source.tar"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(tex, arcname="paper.tex")

    result = ingest_local_document(archive)

    try:
        parsed_path = project_path("data/parsed_papers", f"{result['paper_id']}.json")
        chunks_path = project_path("data/document_chunks", f"{result['paper_id']}.jsonl")
        parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
        chunks = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]

        assert parsed["source_format"] == "latex"
        assert {section["section"] for section in parsed["sections"]} >= {"Introduction", "Model", "Empirical Results", "Conclusion"}
        assert any(section["formula_blocks"] for section in parsed["sections"])
        assert all(chunk["source_format"] == "latex" for chunk in chunks)
    finally:
        shutil.rmtree(project_path("data/raw_papers", str(result["paper_id"])), ignore_errors=True)
        for relative_path in (
            project_path("data/parsed_papers", f"{result['paper_id']}.json"),
            project_path("data/document_chunks", f"{result['paper_id']}.jsonl"),
            project_path("data/reading_notes", f"{result['paper_id']}.json"),
            project_path("data/rma_records", f"{result['paper_id']}.jsonl"),
        ):
            relative_path.unlink(missing_ok=True)