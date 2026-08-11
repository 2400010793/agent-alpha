# SciNet dependency

Paper Graph uses SciNet as an independently versioned upstream research
dependency.  Its source tree and nested Git metadata are intentionally not
vendored into this monorepo.

- Repository: `git@github.com:tsinghua-fib-lab/SciNet.git`
- Pinned commit: `ed5c76fb250a4face6224ea834a62e63b47ddabd`
- Expected local path: `paper-graph/SciNet/`

To restore the exact dependency from the monorepo root:

```bash
git clone git@github.com:tsinghua-fib-lab/SciNet.git paper-graph/SciNet
git -C paper-graph/SciNet checkout ed5c76fb250a4face6224ea834a62e63b47ddabd
```
