"""arXiv evidence pack builder."""

from ._legacy import legacy

build_arxiv_evidence_pack = legacy.build_arxiv_evidence_pack

__all__ = ["build_arxiv_evidence_pack"]