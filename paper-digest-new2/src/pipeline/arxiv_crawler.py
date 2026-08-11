"""Continuous arXiv evidence crawler entrypoint."""

from src.pipeline.arxiv_evidence_crawler import crawl_one, main

__all__ = ["crawl_one", "main"]