"""arXiv/DOI/SSRN identifier extraction."""

from __future__ import annotations

import re


def _extract_arxiv_id(url: str) -> str:
	match = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})(?:v\d+)?", url.lower())
	return match.group(1) if match else ""


def _extract_doi(text: str) -> str:
	match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, flags=re.I)
	return match.group(0).rstrip(".,;)").lower() if match else ""


def _extract_ssrn_id(url: str) -> str:
	match = re.search(r"(?:abstract_id=|/abstract=)(\d+)", url.lower())
	return match.group(1) if match else ""


__all__ = ["_extract_arxiv_id", "_extract_doi", "_extract_ssrn_id"]