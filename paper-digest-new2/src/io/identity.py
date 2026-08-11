"""Entry identity and deduplication helpers."""

from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
from typing import Dict, List

from src.arxiv.ids import _extract_arxiv_id, _extract_doi, _extract_ssrn_id


def _normalize_text(text: str) -> str:
	return re.sub(r"\s+", " ", text).strip()


def _canonicalize_url(url: str) -> str:
	raw = url.strip().lower()
	if not raw:
		return ""
	parsed = urllib.parse.urlsplit(raw)
	query_pairs = [
		(key, value)
		for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
		if not key.startswith("utm_") and key not in {"fbclid", "gclid"}
	]
	query = urllib.parse.urlencode(query_pairs)
	path = parsed.path.rstrip("/")
	return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def _canonicalize_title(title: str) -> str:
	text = html.unescape(_normalize_text(title)).lower()
	text = re.sub(r"\([^)]*\)|\[[^\]]*\]|（[^）]*）|【[^】]*】", "", text)
	text = re.sub(r"[\s\-_–—]+", "", text)
	return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _entry_key(url: str, title: str, source_id: str) -> str:
	del source_id
	base = _entry_identity_bases(url, title)[0]
	return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _entry_identity_bases(url: str, title: str) -> List[str]:
	url_norm = _canonicalize_url(url)
	title_norm = _canonicalize_title(title)
	arxiv_id = _extract_arxiv_id(url_norm)
	doi = _extract_doi(f"{url} {title}")
	ssrn_id = _extract_ssrn_id(url_norm)
	bases: List[str] = []
	if arxiv_id:
		bases.append(f"arxiv:{arxiv_id}")
	if doi:
		bases.append(f"doi:{doi}")
	if ssrn_id:
		bases.append(f"ssrn:{ssrn_id}")
	if title_norm:
		bases.append(f"title:{title_norm}")
	if url_norm:
		bases.append(f"url:{url_norm}")
	return bases or ["empty"]


def _entry_identity_keys(url: str, title: str) -> List[str]:
	return [hashlib.sha256(base.encode("utf-8")).hexdigest() for base in _entry_identity_bases(url, title)]


def _row_entry_key(row: Dict[str, object]) -> str:
	return _entry_key(
		url=str(row.get("url", "")),
		title=str(row.get("title", "")),
		source_id=str(row.get("source_id", "")),
	)


def _row_identity_keys(row: Dict[str, object]) -> List[str]:
	return _entry_identity_keys(url=str(row.get("url", "")), title=str(row.get("title", "")))


__all__ = [
	"_canonicalize_url",
	"_canonicalize_title",
	"_entry_key",
	"_entry_identity_bases",
	"_entry_identity_keys",
	"_row_entry_key",
	"_row_identity_keys",
]