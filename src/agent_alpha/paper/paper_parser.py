from __future__ import annotations

import html
import json
import re
import tarfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_alpha.config import project_path


@dataclass(frozen=True)
class ParsedSection:
    section: str
    page: int | None
    text: str
    source_format: str
    formula_blocks: list[str] = field(default_factory=list)
    table_captions: list[str] = field(default_factory=list)
    figure_captions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedPaper:
    doc_id: str
    source_type: str
    source_url: str
    title: str
    authors: list[str]
    published_at: str
    license: str
    source_format: str
    sections: list[ParsedSection]
    parsed_path: str
    created_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n")).strip()


def _strip_html(payload: str) -> str:
    payload = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", payload)
    payload = re.sub(r"(?i)<br\s*/?>", "\n", payload)
    payload = re.sub(r"(?i)</(p|div|section|article|h[1-6])>", "\n", payload)
    payload = re.sub(r"<[^>]+>", " ", payload)
    return html.unescape(payload)


def _source_format_for_path(path: Path, content_type: str = "") -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".tex", ".latex"} or name.endswith((".tar", ".tar.gz", ".tgz")):
        return "latex"
    if suffix in {".html", ".htm"} or content_type.startswith("text/html"):
        return "html"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix == ".json":
        return "metadata"
    return "text"


def _read_pdf(path: Path) -> list[ParsedSection]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF parsing requires optional dependency 'pypdf'") from exc
    reader = PdfReader(str(path))
    sections: list[ParsedSection] = []
    for index, page in enumerate(reader.pages, start=1):
        text = _clean_text(page.extract_text() or "")
        if text:
            sections.append(ParsedSection(section=f"page_{index}", page=index, text=text, source_format="pdf"))
    return sections


def _split_text_sections(text: str, source_format: str) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    current_title = "document"
    current_lines: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match and current_lines:
            sections.append(ParsedSection(section=current_title, page=None, text=_clean_text("\n".join(current_lines)), source_format=source_format))
            current_lines = []
        if match:
            current_title = match.group(1).strip()
        current_lines.append(line)
    if current_lines:
        sections.append(ParsedSection(section=current_title, page=None, text=_clean_text("\n".join(current_lines)), source_format=source_format))
    return [section for section in sections if section.text]


def _latex_sources_from_archive(path: Path) -> list[str]:
    sources: list[str] = []
    with tarfile.open(path) as archive:
        members = [member for member in archive.getmembers() if member.isfile() and member.name.lower().endswith(".tex")]
        members.sort(key=lambda member: member.size, reverse=True)
        for member in members[:8]:
            handle = archive.extractfile(member)
            if handle is None:
                continue
            sources.append(handle.read().decode("utf-8", errors="replace"))
    return sources


def _strip_latex_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r"(?<!\\)%.*$", "", line))
    return "\n".join(lines)


def _extract_latex_blocks(text: str, environments: tuple[str, ...]) -> list[str]:
    blocks: list[str] = []
    for env in environments:
        pattern = re.compile(rf"\\begin\{{{re.escape(env)}\}}(.*?)\\end\{{{re.escape(env)}\}}", re.DOTALL)
        blocks.extend(_clean_text(match.group(1)) for match in pattern.finditer(text) if _clean_text(match.group(1)))
    blocks.extend(_clean_text(match.group(1)) for match in re.finditer(r"\\\[(.*?)\\\]", text, flags=re.DOTALL) if _clean_text(match.group(1)))
    return blocks


def _latex_to_readable_text(text: str) -> str:
    text = re.sub(r"\\(cite|ref|label|url)\*?(\[[^\]]*\])?\{([^}]*)\}", r"\3", text)
    text = re.sub(r"\\(textbf|emph|textit)\{([^}]*)\}", r"\2", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", text)
    text = text.replace("~", " ")
    text = re.sub(r"[{}]", "", text)
    return _clean_text(text)


def _read_latex(text: str) -> list[ParsedSection]:
    text = _strip_latex_comments(text)
    sections: list[ParsedSection] = []
    section_pattern = re.compile(r"\\(section|subsection|subsubsection)\*?\{([^}]*)\}")
    matches = list(section_pattern.finditer(text))
    abstract_match = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, flags=re.DOTALL)
    if abstract_match:
        abstract_text = _latex_to_readable_text(abstract_match.group(1))
        if abstract_text:
            sections.append(ParsedSection(section="Abstract", page=None, text=abstract_text, source_format="latex"))
    if not matches:
        formulas = _extract_latex_blocks(text, ("equation", "align", "gather", "multline", "eqnarray"))
        readable = _latex_to_readable_text(text)
        return sections + [ParsedSection(section="document", page=None, text=readable, source_format="latex", formula_blocks=formulas)] if readable else sections
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        formulas = _extract_latex_blocks(body, ("equation", "align", "gather", "multline", "eqnarray"))
        table_captions = [m.group(1).strip() for m in re.finditer(r"\\caption\{([^}]*)\}", body)]
        figure_captions = table_captions
        readable = _latex_to_readable_text(body)
        if readable or formulas:
            sections.append(
                ParsedSection(
                    section=_latex_to_readable_text(match.group(2)) or match.group(2),
                    page=None,
                    text=readable,
                    source_format="latex",
                    formula_blocks=formulas,
                    table_captions=table_captions,
                    figure_captions=figure_captions,
                )
            )
    return sections


def _read_metadata_json(path: Path) -> list[ParsedSection]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text_parts = [str(payload.get("title", "")), str(payload.get("abstract", "")), str(payload.get("summary", ""))]
    text = _clean_text("\n\n".join(part for part in text_parts if part))
    return [ParsedSection(section="metadata", page=None, text=text, source_format="metadata")] if text else []


def parse_raw_paper(metadata_path: str | Path, output_dir: str | Path = "data/parsed_papers") -> ParsedPaper:
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    raw_path = Path(metadata["raw_path"])
    source_format = _source_format_for_path(raw_path, str(metadata.get("content_type", "")))
    suffix = raw_path.suffix.lower()
    if source_format == "pdf":
        sections = _read_pdf(raw_path)
    elif source_format == "latex" and raw_path.name.lower().endswith((".tar", ".tar.gz", ".tgz")):
        sections = []
        for latex_source in _latex_sources_from_archive(raw_path):
            sections.extend(_read_latex(latex_source))
    elif source_format == "latex":
        sections = _read_latex(raw_path.read_text(encoding="utf-8", errors="replace"))
    elif source_format == "metadata":
        sections = _read_metadata_json(raw_path)
    else:
        text = raw_path.read_text(encoding="utf-8", errors="replace")
        if source_format == "html":
            text = _strip_html(text)
        sections = _split_text_sections(_clean_text(text), source_format)
    parsed_dir = project_path(str(output_dir))
    parsed_dir.mkdir(parents=True, exist_ok=True)
    parsed_path = parsed_dir / f"{metadata['paper_id']}.json"
    parsed = ParsedPaper(
        doc_id=str(metadata["paper_id"]),
        source_type=str(metadata.get("source_type", "")),
        source_url=str(metadata.get("source_url", "")),
        title=str(metadata.get("title", "")),
        authors=list(metadata.get("authors", [])),
        published_at=str(metadata.get("published_at", "")),
        license=str(metadata.get("license", "")),
        source_format=source_format,
        sections=sections,
        parsed_path=str(parsed_path),
        created_at=_now_iso(),
    )
    payload = asdict(parsed)
    payload["sections"] = [asdict(section) for section in sections]
    parsed_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return parsed


def parsed_to_dict(parsed: ParsedPaper) -> dict[str, Any]:
    payload = asdict(parsed)
    payload["sections"] = [asdict(section) for section in parsed.sections]
    return payload