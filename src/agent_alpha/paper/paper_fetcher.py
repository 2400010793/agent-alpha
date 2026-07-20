from __future__ import annotations

import hashlib
import json
import shutil
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_alpha.config import project_path
from agent_alpha.paper.relevance_filter import FetchFilterConfig, evaluate_fetch_gate
from agent_alpha.paper.source_loader import PaperSource


@dataclass(frozen=True)
class RawPaperRecord:
    paper_id: str
    source_id: str
    source_type: str
    source_url: str
    title: str
    authors: list[str]
    published_at: str
    raw_path: str
    metadata_path: str
    content_type: str
    license: str
    created_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_doc_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.strip())
    return safe.strip("-")[:80] or "paper"


def _guess_content_type(path_or_url: str) -> str:
    suffix = Path(urllib.parse.urlparse(path_or_url).path).suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".html": "text/html",
        ".htm": "text/html",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
        ".json": "application/json",
    }.get(suffix, "application/octet-stream")


def _write_json_raw(payload: dict[str, Any], source: PaperSource, output_dir: str | Path) -> RawPaperRecord:
    source_url = str(payload.get("source_url") or payload.get("url") or payload.get("link") or source.url)
    title = str(payload.get("title") or source_url or source.id)
    paper_id = stable_doc_id(source_url or title)
    target_dir = project_path(str(output_dir), paper_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    raw_path = target_dir / "entry.json"
    metadata_path = target_dir / "metadata.json"
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    record = RawPaperRecord(
        paper_id=paper_id,
        source_id=source.id,
        source_type=str(payload.get("source_type") or source.source_type or source.type),
        source_url=source_url,
        title=title,
        authors=list(payload.get("authors", [])),
        published_at=str(payload.get("published_at") or payload.get("published") or ""),
        raw_path=str(raw_path),
        metadata_path=str(metadata_path),
        content_type="application/json",
        license=str(payload.get("license", "")),
        created_at=_now_iso(),
    )
    metadata_path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def fetch_local_path(path: str | Path, source: PaperSource, output_dir: str | Path = "data/raw_papers") -> RawPaperRecord:
    input_path = Path(path).expanduser()
    if not input_path.is_absolute():
        input_path = project_path(str(input_path))
    if not input_path.exists():
        raise FileNotFoundError(f"local paper not found: {input_path}")
    paper_id = stable_doc_id(str(input_path.resolve()))
    target_dir = project_path(str(output_dir), paper_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    raw_path = target_dir / f"{_safe_name(input_path.stem)}{input_path.suffix.lower()}"
    if input_path.resolve() != raw_path.resolve():
        shutil.copy2(input_path, raw_path)
    metadata_path = target_dir / "metadata.json"
    record = RawPaperRecord(
        paper_id=paper_id,
        source_id=source.id,
        source_type=source.source_type or source.type,
        source_url=input_path.resolve().as_uri(),
        title=input_path.stem.replace("_", " ").replace("-", " ").strip(),
        authors=[],
        published_at="",
        raw_path=str(raw_path),
        metadata_path=str(metadata_path),
        content_type=_guess_content_type(str(input_path)),
        license="",
        created_at=_now_iso(),
    )
    metadata_path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def fetch_url_to_raw(url: str, source: PaperSource, output_dir: str | Path = "data/raw_papers", timeout_sec: int = 20, user_agent: str = "agent-alpha-paper-reader/0.1") -> RawPaperRecord:
    paper_id = stable_doc_id(url)
    target_dir = project_path(str(output_dir), paper_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout_sec) as response:
        payload = response.read()
        content_type = response.headers.get_content_type() or _guess_content_type(url)
    suffix = Path(urllib.parse.urlparse(url).path).suffix or ".bin"
    raw_path = target_dir / f"download{suffix}"
    raw_path.write_bytes(payload)
    metadata_path = target_dir / "metadata.json"
    record = RawPaperRecord(
        paper_id=paper_id,
        source_id=source.id,
        source_type=source.source_type or source.type,
        source_url=url,
        title=Path(urllib.parse.urlparse(url).path).stem or url,
        authors=[],
        published_at="",
        raw_path=str(raw_path),
        metadata_path=str(metadata_path),
        content_type=content_type,
        license="",
        created_at=_now_iso(),
    )
    metadata_path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def fetch_source(
    source: PaperSource,
    output_dir: str | Path = "data/raw_papers",
    timeout_sec: int = 20,
    user_agent: str = "agent-alpha-paper-reader/0.1",
    max_items: int = 20,
    fetch_filter: FetchFilterConfig | dict[str, Any] | None = None,
) -> list[RawPaperRecord]:
    if source.type == "local":
        records: list[RawPaperRecord] = []
        patterns = source.paths or ((source.url,) if source.url else ())
        for pattern in patterns:
            root_pattern = Path(pattern).expanduser()
            if root_pattern.is_absolute():
                matches = sorted(root_pattern.parent.glob(root_pattern.name))
            else:
                matches = sorted(project_path().glob(pattern))
            for match in matches[: source.max_items or max_items]:
                if match.is_file():
                    records.append(fetch_local_path(match, source, output_dir=output_dir))
        return records
    if source.type in {"web", "url", "html", "pdf"}:
        if not source.url:
            return []
        if fetch_filter is not None:
            cfg = fetch_filter if isinstance(fetch_filter, FetchFilterConfig) else FetchFilterConfig.from_mapping(fetch_filter)
            gate = evaluate_fetch_gate({"source_url": source.url, "title": source.source_name, "source_type": source.source_type}, cfg)
            if not gate.should_fetch:
                return []
        return [fetch_url_to_raw(source.url, source, output_dir=output_dir, timeout_sec=timeout_sec, user_agent=user_agent)]
    if source.type in {"rss", "atom", "arxiv"}:
        entries = fetch_feed_entries(source, timeout_sec=timeout_sec, user_agent=user_agent, max_items=source.max_items or max_items)
        cfg = fetch_filter if isinstance(fetch_filter, FetchFilterConfig) else FetchFilterConfig.from_mapping(fetch_filter or source.extra.get("fetch_filter"))
        records: list[RawPaperRecord] = []
        for entry in entries:
            gate = evaluate_fetch_gate(entry, cfg)
            if not gate.should_fetch:
                continue
            entry = {**entry, "fetch_gate": gate.to_dict()}
            if cfg.download_full_text and entry.get("source_url"):
                records.append(fetch_url_to_raw(str(entry["source_url"]), source, output_dir=output_dir, timeout_sec=timeout_sec, user_agent=user_agent))
            else:
                records.append(_write_json_raw(entry, source, output_dir))
        return records
    raise ValueError(f"unsupported paper source type: {source.type}")


def fetch_feed_entries(source: PaperSource, timeout_sec: int = 20, user_agent: str = "agent-alpha-paper-reader/0.1", max_items: int = 20) -> list[dict[str, Any]]:
    url = source.url
    if source.type == "arxiv":
        params = urllib.parse.urlencode({"search_query": source.query or "cat:q-fin.*", "start": 0, "max_results": max_items, "sortBy": "submittedDate", "sortOrder": "descending"})
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{params}"
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout_sec) as response:
        payload = response.read()
    root = ET.fromstring(payload)
    entries: list[dict[str, Any]] = []
    for item in _iter_feed_items(root):
        entries.append(_feed_item_to_record(item, source))
        if len(entries) >= max_items:
            break
    return entries


def _iter_feed_items(root: ET.Element) -> list[ET.Element]:
    channel_items = root.findall(".//item")
    if channel_items:
        return channel_items
    return list(root.findall("{http://www.w3.org/2005/Atom}entry"))


def _find_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for name in names:
        found = element.find(name)
        if found is not None and found.text:
            return found.text.strip()
        found = element.find(f"{{http://www.w3.org/2005/Atom}}{name}")
        if found is not None and found.text:
            return found.text.strip()
    return ""


def _feed_item_to_record(item: ET.Element, source: PaperSource) -> dict[str, Any]:
    title = _find_text(item, ("title",))
    summary = _find_text(item, ("summary", "description"))
    published = _find_text(item, ("published", "updated", "pubDate"))
    link = _find_text(item, ("link", "id", "guid"))
    for link_element in item.findall("{http://www.w3.org/2005/Atom}link"):
        href = link_element.attrib.get("href")
        rel = link_element.attrib.get("rel", "alternate")
        if href and rel == "alternate":
            link = href
            break
    authors = [_find_text(author, ("name",)) for author in item.findall("{http://www.w3.org/2005/Atom}author")]
    return {
        "source_type": source.source_type or source.type,
        "source_url": link or source.url,
        "title": title,
        "authors": [author for author in authors if author],
        "published_at": published,
        "abstract": summary,
        "source_name": source.source_name,
    }


def record_to_dict(record: RawPaperRecord) -> dict[str, Any]:
    return asdict(record)