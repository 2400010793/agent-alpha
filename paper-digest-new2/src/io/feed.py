"""RSS, Atom, sitemap, and small HTML extraction helpers."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List, Optional


def _normalize_text(text: str) -> str:
	return re.sub(r"\s+", " ", text).strip()


def _find_text(node: ET.Element, names: Iterable[str], ns: Optional[Dict[str, str]] = None) -> str:
	for name in names:
		found = node.find(name, ns or {})
		if found is not None and found.text:
			return _normalize_text(found.text)
	return ""


def _html_attr(tag: str, attr: str) -> str:
	match = re.search(rf"\s{re.escape(attr)}=[\"']([^\"']+)[\"']", tag, flags=re.I)
	return html.unescape(match.group(1)) if match else ""


def _html_meta_content(page_html: str, *names: str) -> str:
	wanted = {name.lower() for name in names}
	for match in re.finditer(r"<meta\b[^>]*>", page_html, flags=re.I):
		tag = match.group(0)
		meta_name = (_html_attr(tag, "property") or _html_attr(tag, "name")).lower()
		if meta_name in wanted:
			content = _html_attr(tag, "content")
			if content:
				return _normalize_text(content)
	return ""


def _html_title(page_html: str) -> str:
	match = re.search(r"<title\b[^>]*>(.*?)</title>", page_html, flags=re.I | re.S)
	if not match:
		return ""
	return _normalize_text(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))))


def parse_sitemap_entries(
	xml_bytes: bytes,
	*,
	timeout_sec: int,
	user_agent: str,
	max_items: int,
	use_proxy: bool = True,
) -> List[Dict[str, str]]:
	from src.io.http import fetch_url

	root = ET.fromstring(xml_bytes)
	ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
	out: List[Dict[str, str]] = []
	url_nodes = root.findall("sm:url", ns) + root.findall("url")
	for node in url_nodes:
		if len(out) >= max_items:
			break
		loc = _find_text(node, ["sm:loc", "loc"], ns)
		if not loc or "/forum/list/" in loc:
			continue
		lastmod = _find_text(node, ["sm:lastmod", "lastmod"], ns)
		try:
			page = fetch_url(loc, timeout_sec=timeout_sec, user_agent=user_agent, use_proxy=use_proxy).decode("utf-8", errors="replace")
		except Exception:
			continue
		title = _html_meta_content(page, "og:title", "twitter:title") or _html_title(page)
		summary = _html_meta_content(page, "og:description", "twitter:description", "description")
		out.append({"title": title, "summary": summary, "url": loc, "published": lastmod})
	return out


def parse_rss_or_atom(xml_bytes: bytes) -> List[Dict[str, str]]:
	root = ET.fromstring(xml_bytes)
	ns = {
		"atom": "http://www.w3.org/2005/Atom",
		"dc": "http://purl.org/dc/elements/1.1/",
		"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
		"rss1": "http://purl.org/rss/1.0/",
	}
	out: List[Dict[str, str]] = []

	if root.tag == "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF":
		for item in root.findall("rss1:item", ns):
			title = _find_text(item, ["rss1:title"], ns)
			summary = _find_text(item, ["rss1:description"], ns)
			link = _find_text(item, ["rss1:link"], ns)
			pub = _find_text(item, ["dc:date"], ns)
			out.append({"title": title, "summary": summary, "url": link, "published": pub})
		return out

	if root.tag.endswith("rss") or root.tag == "rss":
		channel = root.find("channel")
		if channel is None:
			return out
		for item in channel.findall("item"):
			title = _find_text(item, ["title"], ns)
			summary = _find_text(item, ["description", "summary"], ns)
			link = _find_text(item, ["link"], ns)
			pub = _find_text(item, ["pubDate", "dc:date"], ns)
			out.append({"title": title, "summary": summary, "url": link, "published": pub})
		return out

	if root.tag.endswith("feed"):
		for entry in root.findall("atom:entry", ns) + root.findall("entry"):
			title = _find_text(entry, ["atom:title", "title"], ns)
			summary = _find_text(entry, ["atom:summary", "summary", "atom:content", "content"], ns)
			pub = _find_text(entry, ["atom:updated", "updated", "atom:published", "published"], ns)
			link = ""
			link_node = entry.find("atom:link", ns)
			if link_node is None:
				link_node = entry.find("link")
			if link_node is not None:
				link = link_node.attrib.get("href", "") or (link_node.text or "")
			out.append({"title": title, "summary": summary, "url": _normalize_text(link), "published": pub})
	return out


__all__ = ["parse_sitemap_entries", "parse_rss_or_atom"]