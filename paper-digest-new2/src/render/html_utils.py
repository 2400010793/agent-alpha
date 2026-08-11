"""Small HTML helpers and render-time formatting."""

from ._legacy import legacy

_structured_summary_html = legacy._structured_summary_html
_factor_candidate_cards = legacy._factor_candidate_cards
_article_cards = legacy._article_cards

__all__ = ["_structured_summary_html", "_factor_candidate_cards", "_article_cards"]