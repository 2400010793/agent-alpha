"""IO infrastructure: JSONL, config, feed, HTTP, identity, and datetime helpers.

Import concrete helpers from their submodules, for example `src.io.config` or
`src.io.jsonl`. Keeping this package initializer lightweight avoids circular
imports while the legacy pipeline is being split.
"""

__all__: list[str] = []