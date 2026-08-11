"""Dashboard summary, HTML, and browser-side filtering script."""

from ._legacy import legacy

_paper_hf_variant_dashboard = legacy._paper_hf_variant_dashboard
_dashboard_summary = legacy._dashboard_summary
_ratio_text = legacy._ratio_text
_dashboard_html = legacy._dashboard_html
_dashboard_script = legacy._dashboard_script

__all__ = ["_dashboard_summary", "_dashboard_html", "_dashboard_script"]