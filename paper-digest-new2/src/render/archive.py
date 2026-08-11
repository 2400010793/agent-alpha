"""Archive row merge and collection helpers."""

from ._legacy import legacy

_archive_row_score = legacy._archive_row_score
_archive_identity_keys = legacy._archive_identity_keys
_merge_archive_content = legacy._merge_archive_content
merge_article_rows = legacy.merge_article_rows
collect_archive_rows = legacy.collect_archive_rows
build_analysis_archive_rows = legacy.build_analysis_archive_rows
_keep_for_analysis_archive = legacy._keep_for_analysis_archive

__all__ = ["merge_article_rows", "collect_archive_rows", "build_analysis_archive_rows"]