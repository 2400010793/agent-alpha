#!/usr/bin/env python3
"""Fetch high-density OpenAlex API candidates with checkpoints and cost guards."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from paper_graph.filter_profiles import FILTER_PROFILES, get_filter_profile


API_URL = "https://api.openalex.org/works"
USER_AGENT = "paper-graph-openalex-api/0.1"
CHECKPOINT_SCHEMA = "openalex_api_checkpoint_v1"
SUMMARY_SCHEMA = "openalex_api_pilot_summary_v1"
SEARCH_CALL_COST_USD = 0.001
SELECT_FIELDS = (
    "id", "title", "display_name", "authorships", "publication_year",
    "publication_date", "type", "language", "doi", "ids", "primary_topic",
    "topics", "keywords", "concepts", "abstract_inverted_index",
    "primary_location", "best_oa_location", "locations", "referenced_works",
    "referenced_works_count", "cited_by_count", "open_access", "has_content",
    "has_fulltext", "is_retracted", "is_paratext", "is_xpac",
)
CHANNELS = {
    "finance_core": {
        "query": (
            '("algorithmic trading" OR "quantitative trading" OR "statistical arbitrage" '
            'OR "high frequency trading" OR "market microstructure" OR "price discovery" '
            'OR "limit order book" OR "portfolio optimization" OR "asset pricing" '
            'OR "volatility forecasting")'
        ),
        "primary_topic_fields": "20",
    },
    "cross_field_quant": {
        "query": (
            '(("machine learning" OR "deep learning" OR "reinforcement learning" OR transformer) '
            'AND ("stock market" OR "financial market" OR trading OR portfolio OR volatility '
            'OR cryptocurrency))'
        ),
        "primary_topic_fields": "17|20",
    },
}


class DailyLimitReached(RuntimeError):
    """Raised when OpenAlex reports that the daily API budget is exhausted."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def channel_filter(channel: Mapping[str, str], min_date: str) -> str:
    return ",".join((
        f"from_publication_date:{min_date}",
        "type:article|preprint",
        f"primary_topic.field.id:{channel['primary_topic_fields']}",
        f"title_and_abstract.search.exact:{channel['query']}",
    ))


def request_url(*, channel: Mapping[str, str], min_date: str, cursor: str,
                api_key: str | None) -> str:
    params = {
        "filter": channel_filter(channel, min_date),
        "per_page": "100",
        "cursor": cursor,
        "select": ",".join(SELECT_FIELDS),
    }
    if api_key:
        params["api_key"] = api_key
    return f"{API_URL}?{urllib.parse.urlencode(params)}"


def _retry_delay(headers: Mapping[str, str], attempt: int) -> float:
    retry_after = str(headers.get("Retry-After") or "").strip()
    try:
        return min(max(float(retry_after), 1.0), 300.0)
    except ValueError:
        return min(float(2 ** attempt), 60.0)


def request_page(url: str, *, timeout: float, retries: int) -> tuple[dict[str, Any], dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                headers = {key: value for key, value in response.headers.items()}
                if not isinstance(payload, dict):
                    raise ValueError("OpenAlex returned a non-object response")
                return payload, headers
        except urllib.error.HTTPError as error:
            last_error = error
            headers = {key: value for key, value in error.headers.items()}
            if error.code == 429:
                raise DailyLimitReached("OpenAlex daily API limit reached") from error
            if error.code not in {403, 408, 500, 502, 503, 504} or attempt >= retries:
                body = error.read().decode("utf-8", errors="replace")[:1000]
                raise RuntimeError(f"OpenAlex HTTP {error.code}: {body}") from error
            time.sleep(_retry_delay(headers, attempt))
        except (TimeoutError, urllib.error.URLError) as error:
            last_error = error
            if attempt >= retries:
                break
            time.sleep(min(float(2 ** attempt), 60.0))
    raise RuntimeError(f"OpenAlex request failed after {retries + 1} attempts: {last_error}")


def _float_header(headers: Mapping[str, str], name: str) -> float | None:
    lowered = {key.casefold(): value for key, value in headers.items()}
    try:
        return float(lowered[name.casefold()])
    except (KeyError, TypeError, ValueError):
        return None


def load_checkpoint(path: Path, *, config_hash: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": CHECKPOINT_SCHEMA,
            "config_hash": config_hash,
            "total_pages": 0,
            "total_cost_usd": 0.0,
            "channels": {
                name: {"next_cursor": "*", "pages": 0, "complete": False, "reported_count": None}
                for name in CHANNELS
            },
        }
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA:
        raise ValueError("unsupported OpenAlex API checkpoint schema")
    if checkpoint.get("config_hash") != config_hash:
        raise ValueError("OpenAlex API checkpoint configuration changed; use a new output directory")
    return checkpoint


def summarize_pages(output_root: Path, profile_name: str) -> dict[str, Any]:
    profile = get_filter_profile(profile_name)
    unique: dict[str, dict[str, Any]] = {}
    fetched_rows = 0
    channel_rows: Counter[str] = Counter()
    for path in sorted((output_root / "pages").glob("*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        channel = path.parent.name
        results = payload.get("results") or []
        fetched_rows += len(results)
        channel_rows[channel] += len(results)
        for work in results:
            identifier = str(work.get("id") or "")
            if identifier:
                unique.setdefault(identifier, work)

    retrieval: Counter[str] = Counter()
    finance: Counter[str] = Counter()
    value_tiers: Counter[str] = Counter()
    for work in unique.values():
        match = profile.classify(work)
        retrieval[str(match.get("retrieval_tier") or "candidate")] += 1
        audit = profile.audit(work, match)
        finance[audit.status] += 1
        value_tiers[profile.assess_value(work, audit).tier] += 1
    return {
        "schema_version": SUMMARY_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filter_profile": profile_name,
        "fetched_rows": fetched_rows,
        "unique_works": len(unique),
        "cross_channel_duplicates": fetched_rows - len(unique),
        "channel_rows": dict(channel_rows),
        "retrieval_tier": dict(retrieval),
        "finance_status": dict(finance),
        "research_value_tier": dict(value_tiers),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--min-date", default="2016-01-01")
    parser.add_argument("--filter-profile", choices=tuple(FILTER_PROFILES), default="v5")
    parser.add_argument("--max-pages", type=int, default=4, help="maximum API calls in this run")
    parser.add_argument("--max-cost-usd", type=float, default=0.01, help="hard cost cap for this run")
    parser.add_argument("--delay", type=float, default=1.0, help="minimum seconds between successful calls")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=4)
    args = parser.parse_args()
    if args.max_pages < 1:
        raise SystemExit("--max-pages must be at least 1")
    if args.max_cost_usd < SEARCH_CALL_COST_USD:
        raise SystemExit(f"--max-cost-usd must be at least {SEARCH_CALL_COST_USD}")

    api_key = os.environ.get("OPENALEX_API_KEY") or None
    config = {
        "channels": CHANNELS,
        "min_date": args.min_date,
        "select": SELECT_FIELDS,
        "filter_profile": args.filter_profile,
        # Authentication changes quota, not query semantics.  Keeping this
        # stable lets an anonymous pilot resume after a key is configured.
        "authenticated": False,
    }
    config_hash = canonical_hash(config)
    checkpoint_path = args.output_root / "checkpoint.json"
    checkpoint = load_checkpoint(checkpoint_path, config_hash=config_hash)
    run_pages = 0
    run_cost = 0.0
    last_headers: dict[str, str] = {}
    stop_reason = "all_channels_complete"

    while run_pages < args.max_pages:
        progressed = False
        for name, channel in CHANNELS.items():
            state = checkpoint["channels"][name]
            if state["complete"]:
                continue
            if run_pages >= args.max_pages:
                stop_reason = "max_pages"
                break
            if run_cost + SEARCH_CALL_COST_USD > args.max_cost_usd + 1e-12:
                stop_reason = "max_cost_usd"
                break
            remaining_usd = _float_header(last_headers, "X-RateLimit-Remaining-USD")
            if remaining_usd is not None and remaining_usd + 1e-12 < SEARCH_CALL_COST_USD:
                stop_reason = "daily_budget_exhausted"
                break

            url = request_url(
                channel=channel, min_date=args.min_date,
                cursor=str(state["next_cursor"]), api_key=api_key,
            )
            try:
                payload, headers = request_page(url, timeout=args.timeout, retries=args.retries)
            except DailyLimitReached:
                stop_reason = "daily_budget_exhausted"
                break
            meta = payload.get("meta") or {}
            page_number = int(state["pages"]) + 1
            page_path = args.output_root / "pages" / name / f"page-{page_number:06d}.json"
            atomic_json(page_path, payload)
            cost = float(meta.get("cost_usd") or SEARCH_CALL_COST_USD)
            next_cursor = meta.get("next_cursor")
            state.update({
                "next_cursor": next_cursor,
                "pages": page_number,
                "complete": next_cursor is None or not payload.get("results"),
                "reported_count": meta.get("count"),
            })
            checkpoint["total_pages"] = int(checkpoint["total_pages"]) + 1
            checkpoint["total_cost_usd"] = round(float(checkpoint["total_cost_usd"]) + cost, 6)
            checkpoint["last_rate_limit"] = {
                key: value for key, value in headers.items() if key.casefold().startswith("x-ratelimit-")
            }
            atomic_json(checkpoint_path, checkpoint)
            run_pages += 1
            run_cost += cost
            last_headers = headers
            progressed = True
            print(json.dumps({
                "channel": name,
                "page": page_number,
                "rows": len(payload.get("results") or []),
                "reported_count": meta.get("count"),
                "run_pages": run_pages,
                "run_cost_usd": round(run_cost, 6),
                "remaining_usd": _float_header(headers, "X-RateLimit-Remaining-USD"),
            }, ensure_ascii=False), flush=True)
            if args.delay:
                time.sleep(args.delay)
        else:
            if progressed:
                continue
        break

    if run_pages >= args.max_pages:
        stop_reason = "max_pages"
    summary = summarize_pages(args.output_root, args.filter_profile)
    summary.update({
        "authenticated": bool(api_key),
        "run_pages": run_pages,
        "run_cost_usd": round(run_cost, 6),
        "cumulative_pages": checkpoint["total_pages"],
        "cumulative_cost_usd": checkpoint["total_cost_usd"],
        "stop_reason": stop_reason,
        "reported_counts": {
            name: state["reported_count"] for name, state in checkpoint["channels"].items()
        },
    })
    atomic_json(args.output_root / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
