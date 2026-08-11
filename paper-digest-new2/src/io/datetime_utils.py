"""Datetime parsing and arXiv query window helpers."""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Optional, Tuple


def _to_utc_iso(dt: datetime) -> str:
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=timezone.utc)
	return dt.astimezone(timezone.utc).isoformat()


def _parse_datetime_value(raw: Optional[str]) -> Optional[datetime]:
	if not raw:
		return None
	text = raw.strip()
	if not text:
		return None
	try:
		dt = parsedate_to_datetime(text)
	except Exception:
		try:
			dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
		except Exception:
			return None
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=timezone.utc)
	return dt.astimezone(timezone.utc)


def _parse_datetime(raw: Optional[str]) -> str:
	dt = _parse_datetime_value(raw)
	if dt is not None:
		return _to_utc_iso(dt)
	return _to_utc_iso(datetime.now(timezone.utc))


def _is_within_max_age(raw: Optional[str], *, now: datetime, max_age_days: int) -> bool:
	if max_age_days <= 0:
		return True
	dt = _parse_datetime_value(raw)
	if dt is None:
		return True
	return dt >= now - timedelta(days=max_age_days)


def _row_is_within_max_age(row: Dict[str, object], *, now: datetime, max_age_days: int) -> bool:
	return _is_within_max_age(str(row.get("publish_time") or ""), now=now, max_age_days=max_age_days)


def _build_fetch_start_ts(now: datetime, max_age_days: int) -> str:
	if max_age_days <= 0:
		return "190001010000"
	return (now - timedelta(days=max_age_days)).strftime("%Y%m%d%H%M")


def _build_fetch_end_ts(now: datetime) -> str:
	return now.strftime("%Y%m%d%H%M")


def _build_month_window(fetch_month: str) -> Tuple[str, str]:
	if not re.fullmatch(r"\d{6}", fetch_month):
		raise ValueError("fetch month must be YYYYMM")
	year = int(fetch_month[:4])
	month = int(fetch_month[4:6])
	last_day = calendar.monthrange(year, month)[1]
	return (f"{fetch_month}010000", f"{fetch_month}{last_day:02d}2359")


def _build_arxiv_query_window(fetch_month: str, now: datetime, max_age_days: int) -> Tuple[str, str]:
	if fetch_month:
		return _build_month_window(fetch_month)
	return _build_fetch_start_ts(now, max_age_days), _build_fetch_end_ts(now)


__all__ = [
	"_to_utc_iso",
	"_parse_datetime_value",
	"_parse_datetime",
	"_is_within_max_age",
	"_row_is_within_max_age",
	"_build_fetch_start_ts",
	"_build_fetch_end_ts",
	"_build_arxiv_query_window",
	"_build_month_window",
]