# Libraries and Coding Guidelines

Assume the generated factor file may use:

```python
import numpy as np
import pandas as pd
```

Coding rules:

- Do not use nested loops.
- Prefer vectorized pandas/numpy operations.
- Convert numeric inputs with `pd.to_numeric(..., errors="coerce")` when robustness matters.
- Add small epsilons to denominators.
- Keep output finite when possible; allow NaN when the historical window is insufficient.
- Do not mutate the caller's input DataFrame in place; use local Series variables or `df.copy()` only when necessary.
- Do not read files, call APIs, or access databases inside `compute_factor`.
- Do not import project internals inside generated factor files unless explicitly allowed later.
- Do not use `ret10s`, `ret30s`, `ret60s`, or `ret120s` in factor computations.

Recommended helper idioms:

```python
eps = 1e-12
bid_v = pd.to_numeric(df["bidV1"], errors="coerce")
ask_v = pd.to_numeric(df["askV1"], errors="coerce")
imbalance = (bid_v - ask_v) / (bid_v + ask_v + eps)
```