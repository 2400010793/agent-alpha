from __future__ import annotations


def cogalpha_role_mapping() -> dict[str, str]:
    """Return CogAlpha roles that can be rewritten for HF factor generation."""
    return {
        "AgentOrderImbalance": "委托失衡、盘口压力、买卖盘强弱",
        "AgentLiquidity": "bid-ask spread、盘口厚度、冲击成本、流动性恢复",
        "AgentPriceVolumeCoherence": "短窗口量价协同与背离",
        "AgentVolumeStructure": "成交节律、成交额突变、量能聚集",
        "AgentReversal": "10s-30min 短期反转",
        "AgentDailyTrend": "短周期趋势 / micro momentum",
        "AgentRangeVol": "短窗口波动压缩、扩张、range burst",
        "AgentVolatilityRegime": "高频波动状态切换",
        "AgentBarShape": "分钟 bar / tick bar 形态",
        "AgentComposite": "多个高频机制的组合与正交化",
    }