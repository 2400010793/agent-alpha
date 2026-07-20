---
name: supported_fields_and_asl
description: "Use when: choosing fields and ASL ops for Agent Alpha FactorCandidate JSON; lists renderer-supported ASL ops, safe field families, forbidden historical aliases, and expression rendering boundaries."
---

# supported_fields_and_asl

Use this capability map before choosing `prefix_expression`, `fields`, or `expression` for a `FactorCandidate`.

## Renderer Boundary

- `prefix_expression` is the source of truth.
- `expression` is only a readable compatibility view and must be derived from `prefix_expression`.
- Do not invent free-form expression strings. The renderer is intentionally small and will reject unsupported AST calls.
- Safe pattern: emit valid `prefix_expression`; the system can derive `expression`, `fields`, and `windows` from it.
- Unsafe pattern: writing arbitrary strings such as `safe_div(spread_l1, 10)` without matching valid prefix structure.

## Supported ASL Ops

Use only these exact lowercase op names:

```text
add
sub
mul
div
neg
safe_div
zscore
rolling_mean
rolling_std
rolling_sum
abs
clip
log1p
log
tanh
sign
rank
max
min
gt
lt
ge
le
eq
neq
and
or
where
diff
shift
pct_change
ewm_mean
ewm_std
rolling_min
rolling_max
rolling_median
rolling_rank
rolling_count
rolling_corr
rolling_cov
rolling_beta
div_mean
div_std
vol_scale
```

Unsupported unless explicitly added later:

```text
cond
ifelse
maximum
minimum
beta
```

## Safe Raw Fields

These raw fields are safe current/historical inputs:

```text
close
volume
money
totalDeputeBuy
totalDeputeSell
averageBuy
averageSell
last_close
askP1 askP2 askP3 askP4 askP5 askP6 askP7 askP8 askP9 askP10
bidP1 bidP2 bidP3 bidP4 bidP5 bidP6 bidP7 bidP8 bidP9 bidP10
askV1 askV2 askV3 askV4 askV5 askV6 askV7 askV8 askV9 askV10
bidV1 bidV2 bidV3 bidV4 bidV5 bidV6 bidV7 bidV8 bidV9 bidV10
```

Avoid entity/time columns in alpha formulas unless explicitly needed: `code`, `ticker`, `date`, `delay_time`, `processing_time`.

## Safe Derived Fields

The registry permits many derived fields, but the controlled renderer currently computes only a small stable subset directly:

```text
spread_l1
relative_spread_l1
mid_price_l1
microprice_l1
depth_imbalance_l1
log_volume
volume_shock_20_120
activity_surge_20_120
```

Prefer raw fields when possible for smoke tests. Use derived fields only when they appear in the allowed field payload and the mechanism needs them.

## Historical Field Aliases To Avoid

Do not use these old fac-idea names directly in Agent Alpha candidates unless they are explicitly mapped by the prompt payload:

```text
open
high
low
midP
wmidP
ret_mid
trade_vol
```

Safer approximations when needed:

```text
midP -> mid_price_l1 or close
wmidP -> microprice_l1 or weighted_mid_price_l1
trade_vol -> volume
ret_mid -> close_return_1tick or close_log_return_1tick
open -> session_open_price only if allowed and mechanism requires it
```

## Label And Blocked Fields

Never use:

```text
ret10s
ret30s
ret60s
ret120s
industry
sector
sentiment
news_score
analyst_rating
revenue
earnings
macro
index_return
benchmark_return
fundamentals
financial_statement
analyst_forecast
social_media
news_event
```

## Robust Smoke-Test Patterns

Order-book imbalance:

```json
["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]]
```

Spread-adjusted imbalance:

```json
["mul", ["safe_div", ["sub", "bidV1", "askV1"], ["add", "bidV1", "askV1"]], ["zscore", "relative_spread_l1", 60]]
```

Activity pressure:

```json
["mul", ["zscore", "volume", 60], ["zscore", "close", 20]]
```

If the desired idea requires unsupported conditionals or EWM operators, simplify the mechanism into a supported continuous proxy or return fewer candidates.
