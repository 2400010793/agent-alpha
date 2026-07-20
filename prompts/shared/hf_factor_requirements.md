# High-Frequency Factor Requirements

The target alpha horizon is 30 seconds to 30 minutes.

Each generated factor must:

- Be designed for tick-level or short intraday windows.
- Use only current and historical observations available up to `delay_time`.
- Avoid all future labels and forward-looking aggregations.
- Be compatible with `fac-eval-demo`:
  - declare module variable `fields = ["factor_column_name", ...]`;
  - define `compute_factor(code, date, df) -> pandas.DataFrame`;
  - return a DataFrame with the same logical length as `df`;
  - return one column for each field listed in `fields`.
- Include a concise economic rationale tied to a high-frequency mechanism.
- Prefer simple, auditable constructions over opaque formula stacking.
- Use bounded or normalized forms when raw magnitudes are unstable.
- Preserve causality: rolling, expanding, EWMA, cumulative, and lagged features must use only past/current rows.

The factor should be interpretable as one of these mechanisms:

```text
order_book_pressure
depute_imbalance
trade_impact
price_volume_divergence
spread_liquidity
short_reversal
short_momentum
volatility_burst
book_shape
trading_rhythm
```