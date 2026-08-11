# Third-party scientometrics references

This directory contains pinned reference source, not production runtime dependencies.

## pySciSci

`pyscisci/` is the source distribution for pySciSci 0.92. Its provenance and
checksum are recorded in `pyscisci/.source.json`; its upstream MIT license is
preserved in `pyscisci/LICENSE`.

The project may use pySciSci on small deterministic fixtures as an independent
parity oracle for Uzzi novelty/conventionality and the disruption index. The
full OpenAlex computation must be implemented in the Paper Graph pipeline with
versioned Parquet/DuckDB inputs, an explicit observation cutoff, deterministic
random seeds, metric variants, and coverage/maturity fields. Nothing under this
directory is imported by the production package.

## SciNet

The existing SciNet checkout remains at `../SciNet`, pinned to commit
`ed5c76fb250a4face6224ea834a62e63b47ddabd`, which matched upstream HEAD when
audited on 2026-08-11. It is used only for query fixtures, output-format
compatibility, and evaluator behavior audits.

SciNet's README describes the project as MIT, but the audited checkout has no
standalone license file. Do not copy or import its implementation into the
production package until the upstream licensing artifact is clarified.

## Excluded runtime dependencies

- Novelpy 1.4 is an optional MIT-licensed secondary oracle. Its PyPI source
  distribution is pinned in `configs/scientometrics_references_v1.json`, but it
  is not vendored because the package metadata does not identify an upstream
  repository and its workflow is oriented around JSON/MongoDB processing.
- cdindex and fast-cdindex are GPL-licensed references. They are not vendored,
  linked, imported, or required by this project. Any future use requires an
  explicit licensing decision.
