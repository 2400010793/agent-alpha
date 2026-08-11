"""Daily, archive, and home page rendering."""

from ._legacy import legacy

build_history = legacy.build_history
render_daily_page = legacy.render_daily_page
render_archive_page = legacy.render_archive_page
render_home_page = legacy.render_home_page

__all__ = ["build_history", "render_daily_page", "render_archive_page", "render_home_page"]