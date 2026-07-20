from __future__ import annotations

# Backward-compatible wrapper. The fac-eval data contract now belongs to factors.
from agent_alpha.factors.fac_eval_contract import FacEvalContract as MarketDataClient
from agent_alpha.factors.fac_eval_contract import FacEvalDataConfig as MarketDataConfig

__all__ = ["MarketDataClient", "MarketDataConfig"]