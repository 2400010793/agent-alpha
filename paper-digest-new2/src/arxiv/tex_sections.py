"""TeX section parsing helpers."""

from ._legacy import legacy

_tex_sections = legacy._tex_sections
_is_tail_section = legacy._is_tail_section
_extract_tex_section_overview = legacy._extract_tex_section_overview
_extract_tex_section_snippets = legacy._extract_tex_section_snippets

__all__ = ["_tex_sections", "_extract_tex_section_overview", "_extract_tex_section_snippets"]