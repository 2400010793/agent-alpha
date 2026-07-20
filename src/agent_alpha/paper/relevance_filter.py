from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any


DEFAULT_INCLUDE_KEYWORDS = (
    "high-frequency",
    "intraday",
    "tick",
    "order book",
    "limit order book",
    "microstructure",
    "liquidity",
    "spread",
    "order imbalance",
    "trade flow",
    "volume",
    "market making",
    "transaction cost",
    "高频",
    "日内",
    "盘口",
    "订单簿",
    "微观结构",
    "流动性",
    "价差",
    "成交量",
)

DEFAULT_EXCLUDE_KEYWORDS = (
    "annual report",
    "earnings call",
    "fundamental",
    "macro",
    "analyst forecast",
    "sentiment only",
    "portfolio choice only",
    "monthly anomaly only",
    "基本面",
    "财报",
    "宏观",
    "分析师",
)


@dataclass(frozen=True)
class FetchFilterConfig:
    min_include_keyword_hits: int = 1
    require_hf_context: bool = True
    max_age_days: int = 1095
    allowed_source_types: tuple[str, ...] = ("paper", "research_blog", "blog", "local_document")
    include_keywords: tuple[str, ...] = DEFAULT_INCLUDE_KEYWORDS
    exclude_keywords: tuple[str, ...] = DEFAULT_EXCLUDE_KEYWORDS
    download_full_text: bool = False

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> "FetchFilterConfig":
        payload = payload or {}
        return cls(
            min_include_keyword_hits=int(payload.get("min_include_keyword_hits", 1)),
            require_hf_context=bool(payload.get("require_hf_context", True)),
            max_age_days=int(payload.get("max_age_days", 1095)),
            allowed_source_types=tuple(str(x) for x in payload.get("allowed_source_types", cls.allowed_source_types)),
            include_keywords=tuple(str(x) for x in payload.get("include_keywords", DEFAULT_INCLUDE_KEYWORDS)),
            exclude_keywords=tuple(str(x) for x in payload.get("exclude_keywords", DEFAULT_EXCLUDE_KEYWORDS)),
            download_full_text=bool(payload.get("download_full_text", False)),
        )


@dataclass(frozen=True)
class FetchGateDecision:
    should_fetch: bool
    score: int
    include_hits: list[str] = field(default_factory=list)
    exclude_hits: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_fetch_gate(entry: dict[str, Any], config: FetchFilterConfig | None = None) -> FetchGateDecision:
    cfg = config or FetchFilterConfig()
    text = " ".join(str(entry.get(key, "")) for key in ("title", "abstract", "summary", "source_url", "url")).casefold()
    include_hits = sorted({keyword for keyword in cfg.include_keywords if keyword.casefold() in text})
    exclude_hits = sorted({keyword for keyword in cfg.exclude_keywords if keyword.casefold() in text})
    reasons: list[str] = []
    source_type = str(entry.get("source_type", "paper"))
    if cfg.allowed_source_types and source_type not in cfg.allowed_source_types:
        reasons.append(f"source_type_not_allowed:{source_type}")
    if len(include_hits) < cfg.min_include_keyword_hits:
        reasons.append(f"include_keyword_hits_too_low:{len(include_hits)}<{cfg.min_include_keyword_hits}")
    if cfg.require_hf_context and not include_hits:
        reasons.append("missing_high_frequency_context")
    if exclude_hits and not include_hits:
        reasons.append(f"excluded_context_only:{','.join(exclude_hits)}")
    published_at = str(entry.get("published_at") or entry.get("published") or "")
    if cfg.max_age_days > 0 and published_at:
        age_days = _age_days(published_at)
        if age_days is not None and age_days > cfg.max_age_days:
            reasons.append(f"too_old:{age_days}>{cfg.max_age_days}")
    return FetchGateDecision(
        should_fetch=not reasons,
        score=len(include_hits) - len(exclude_hits),
        include_hits=include_hits,
        exclude_hits=exclude_hits,
        reasons=reasons,
    )


def _age_days(value: str) -> int | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return max(0, (datetime.now(timezone.utc) - parsed).days)


def _parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)