"""arXiv source archive extraction and main TeX selection."""

from ._legacy import legacy

_select_main_tex_source = legacy._select_main_tex_source
_is_likely_non_article_source = legacy._is_likely_non_article_source
_assemble_arxiv_tex_corpus = legacy._assemble_arxiv_tex_corpus
_decode_arxiv_source_file = legacy._decode_arxiv_source_file
_extract_arxiv_source_texts = legacy._extract_arxiv_source_texts

__all__ = ["_select_main_tex_source", "_assemble_arxiv_tex_corpus", "_extract_arxiv_source_texts"]