# High-Frequency Field Constraints

Use only fields declared by `configs/field_registry.yaml`.

Raw input fields include tick-level price, volume, notional, order-book, and order-delegation fields such as:

```text
close, volume, money, totalDeputeBuy, totalDeputeSell, averageBuy, averageSell, last_close
askP1 ... askP10, bidP1 ... bidP10
askV1 ... askV10, bidV1 ... bidV10
delay_time, processing_time, date, code
```

Whitelisted derived feature names may be used as design targets only when they can be computed from current or historical raw fields. Examples:

```text
mid_price_l1, microprice_l1, spread_l1, relative_spread_l1
depth_imbalance_l1, depth_imbalance_l5, book_imbalance_l10
volume_shock_20_120, money_shock_20_120
realized_vol_mid_60, microstructure_noise_trace_60
obi_return_pressure_20_l5, spread_obi_slippage_risk_l5
```

Never use forward-return label fields as factor inputs:

```text
ret10s, ret30s, ret60s, ret120s
```

These labels are evaluation targets only. Referencing them inside a factor expression is label leakage and must be rejected.

Do not use fundamentals, analyst data, news, social media, macro data, industry labels, external index returns, or any private data unless they are only mentioned as non-executable research context.