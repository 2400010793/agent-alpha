# Output Format

Return only plain Python code. Do not wrap the answer in Markdown.

The output must be one complete fac-eval-compatible factor file:

```python
from __future__ import annotations

import numpy as np
import pandas as pd

fields = ["alpha_example"]


def compute_factor(code: str, date: str, df: pd.DataFrame) -> pd.DataFrame:
    """Short economic explanation and formula summary."""
    # factor computation
    return pd.DataFrame({"alpha_example": alpha})
```

Requirements:

- `fields` must exactly match the returned DataFrame columns.
- `compute_factor` must be deterministic.
- Output columns must not be named like labels.
- The factor file must compile with `python -m py_compile`.
- The factor file must not contain explanations outside code comments/docstrings.