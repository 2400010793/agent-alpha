from __future__ import annotations


def summarize_metrics(metrics: dict) -> dict:
    """Normalize fac-eval metric payloads for The Evaluator."""
    return dict(metrics)