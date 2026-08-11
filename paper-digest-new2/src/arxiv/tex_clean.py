"""TeX pre-cleaning and command stripping."""

from ._legacy import legacy

_strip_tex_preamble = legacy._strip_tex_preamble
_tex_unescape = legacy._tex_unescape
pre_clean_tex = legacy.pre_clean_tex
_strip_tex_commands = legacy._strip_tex_commands
_clip_snippet = legacy._clip_snippet
_normalize_tex_ref = legacy._normalize_tex_ref

__all__ = ["pre_clean_tex", "_strip_tex_commands", "_clip_snippet"]