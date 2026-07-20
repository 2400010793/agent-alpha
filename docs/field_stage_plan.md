# Field Stage Plan

This stage defines the field contract before any paper crawler or full agent loop is implemented.

## What We Learned From fac-eval-demo

`fac-eval-demo` evaluates factor files with this contract:

```text
module variable: fields = ["factor_column_name", ...]
function: compute_factor(code, date, df) -> pandas.DataFrame
input df: one stock on one date, sorted by delay_time
output DataFrame: same logical length as df, one column per factor field
labels: horizon columns such as ret60s already exist in df
```

The evaluator reads data from:

```text
trade_data_dir / date / code.parquet
```

Important columns:

```text
code
delay_time
processing_time
date
close
volume
money
totalDeputeBuy / totalDeputeSell
averageBuy / averageSell
last_close
askP1 ... askP10
bidP1 ... bidP10
askV1 ... askV10
bidV1 ... bidV10
ret10s / ret30s / ret60s / ret120s as labels
```

Observed sample:

```text
file: /data/share/py-eval/trade_data/20250306/002938.parquet
shape: 17564 rows x 56 columns
time range: 2025-03-06 09:30:00.280413 -> 2025-03-06 14:56:00.938603
timestamp granularity: tick-level, microsecond-resolution delay_time
```

## Field Work Scope

Implemented now:

```text
configs/field_registry.yaml
configs/market_data.yaml
src/agent_alpha/rag/field_registry.py
src/agent_alpha/data_interfaces/data_guard.py
src/agent_alpha/data_interfaces/hf_feature_builder.py
src/agent_alpha/data_interfaces/market_data_client.py
```

This means the project can already:

```text
load the high-frequency field whitelist
separate raw input fields from derived feature vocabulary
identify label leakage fields
reject blocked research fields
extract fields from candidate expressions
describe the fac-eval market data contract
generate basic historical high-frequency derived features
```

## Field Registry v2

`configs/field_registry.yaml` now has three important field groups:

```text
allowed_input_fields
  Raw columns observed in the parquet files. These can be read directly as current or historical inputs.

label_fields
  Forward-return labels such as ret10s, ret30s, ret60s, ret120s. These are evaluation targets only.

derived_feature_fields
  Whitelisted feature names that can be derived later from price, volume, notional, timestamp, and order-book fields.
```

The derived field list is only a vocabulary and permission layer. It intentionally does not define calculation functions yet.

Derived feature families currently include:

```text
price anchors and tick returns
spread and execution friction
depth and order-book imbalance
queue/depth change and replenishment proxies
activity, flow, and notional proxies
volatility, noise, and state features
interaction proxies inspired by proxy_variant_templates.yaml
```

## Hard Rules

```text
ret10s / ret30s / ret60s / ret120s are labels, not input features.
Generated factor expressions must not reference label fields.
Fundamental, news, sentiment, analyst, macro, industry, and external index fields are blocked.
Derived feature fields are allowed as names, but their calculation functions are not implemented in this stage.
The Implementer must output fac-eval compatible factor files only after data_guard passes.
```

## Next Coding Step

The next implementation step should be:

```text
FactorCandidate
  -> expression_validator
  -> fac-eval factor file renderer
  -> py_compile validation
  -> fac-eval config writer
```

The paper crawler remains out of scope and should be handled by the separate crawler AI described in `docs/crawler_handoff.md`.