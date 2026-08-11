"""HTTP and feed fetch helpers."""

from __future__ import annotations

import multiprocessing as mp
import queue
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from src.io.config import SourceConfig
from src.io.datetime_utils import _build_arxiv_query_window
from src.io.feed import parse_rss_or_atom, parse_sitemap_entries


def fetch_url(url: str, timeout_sec: int, user_agent: str, *, use_proxy: bool = True) -> bytes:
	req = urllib.request.Request(url, headers={"User-Agent": user_agent})
	opener = urllib.request.build_opener() if use_proxy else urllib.request.build_opener(urllib.request.ProxyHandler({}))
	with opener.open(req, timeout=timeout_sec) as resp:
		return resp.read()


def fetch_entries_for_source(
	src: SourceConfig,
	*,
	timeout_sec: int,
	user_agent: str,
	max_items: int,
	fetch_month: str,
	fetch_now: datetime,
	max_age_days: int,
) -> List[Dict[str, str]]:
	if src.local_file:
		local_path = Path(src.local_file).expanduser()
		if not local_path.exists():
			return []
		payload = local_path.read_bytes()
		if src.feed_type == "sitemap":
			return parse_sitemap_entries(payload, timeout_sec=timeout_sec, user_agent=user_agent, max_items=max_items, use_proxy=src.use_proxy)
		return parse_rss_or_atom(payload)

	if "rss.arxiv.org/rss/" in src.url:
		category = src.url.rstrip("/").split("/")[-1]
		if category == "q-fin":
			category = "q-fin.*"
		start_ts, end_ts = _build_arxiv_query_window(fetch_month, fetch_now, max_age_days)
		query = f"(cat:{category}) AND submittedDate:[{start_ts} TO {end_ts}]"
		params = urllib.parse.urlencode(
			{
				"search_query": query,
				"start": 0,
				"max_results": max_items,
				"sortBy": "submittedDate",
				"sortOrder": "descending",
			}
		)
		api_url = f"https://export.arxiv.org/api/query?{params}"
		payload = fetch_url(api_url, timeout_sec=timeout_sec, user_agent=user_agent, use_proxy=src.use_proxy)
		return parse_rss_or_atom(payload)

	payload = fetch_url(src.url, timeout_sec=timeout_sec, user_agent=user_agent, use_proxy=src.use_proxy)
	if src.feed_type == "sitemap":
		return parse_sitemap_entries(payload, timeout_sec=timeout_sec, user_agent=user_agent, max_items=max_items, use_proxy=src.use_proxy)
	return parse_rss_or_atom(payload)


def _raise_source_timeout(signum: int, frame: object) -> None:
	del signum, frame
	raise TimeoutError("source fetch exceeded source_timeout_sec")


def _fetch_entries_worker(
	result_queue: object,
	src: SourceConfig,
	timeout_sec: int,
	user_agent: str,
	max_items: int,
	fetch_month: str,
	fetch_now_iso: str,
	max_age_days: int,
) -> None:
	try:
		fetch_now = datetime.fromisoformat(fetch_now_iso)
		entries = fetch_entries_for_source(
			src,
			timeout_sec=timeout_sec,
			user_agent=user_agent,
			max_items=max_items,
			fetch_month=fetch_month,
			fetch_now=fetch_now,
			max_age_days=max_age_days,
		)[:max_items]
		result_queue.put(("ok", entries))
	except Exception as exc:
		result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def fetch_entries_for_source_with_timeout(
	src: SourceConfig,
	*,
	timeout_sec: int,
	source_timeout_sec: int,
	user_agent: str,
	max_items: int,
	fetch_month: str,
	fetch_now: datetime,
	max_age_days: int,
) -> List[Dict[str, str]]:
	if source_timeout_sec <= 0:
		return fetch_entries_for_source(
			src,
			timeout_sec=timeout_sec,
			user_agent=user_agent,
			max_items=max_items,
			fetch_month=fetch_month,
			fetch_now=fetch_now,
			max_age_days=max_age_days,
		)[:max_items]
	ctx = mp.get_context("fork")
	result_queue = ctx.Queue(maxsize=1)
	process = ctx.Process(
		target=_fetch_entries_worker,
		args=(result_queue, src, timeout_sec, user_agent, max_items, fetch_month, fetch_now.isoformat(), max_age_days),
	)
	process.start()
	process.join(source_timeout_sec)
	if process.is_alive():
		process.terminate()
		process.join(5)
		if process.is_alive():
			process.kill()
			process.join()
		raise TimeoutError(f"source fetch exceeded {source_timeout_sec}s")
	try:
		status, payload = result_queue.get_nowait()
	except queue.Empty:
		if process.exitcode == 0:
			return []
		raise RuntimeError(f"source fetch worker exited with code {process.exitcode}")
	if status == "error":
		raise RuntimeError(str(payload))
	return payload


__all__ = ["fetch_url", "fetch_entries_for_source", "fetch_entries_for_source_with_timeout"]