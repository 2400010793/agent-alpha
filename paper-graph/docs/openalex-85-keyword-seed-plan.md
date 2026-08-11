# OpenAlex 85-keyword candidate and seed-graph plan

## 1. Objective and scope

The pipeline will build an auditable OpenAlex corpus for the exact 85 terms in
`my-paper-digest-new2/config/sources.yaml`, recover arXiv identities where exact
evidence exists, and test whether eligible papers can serve as Paper Graph
seeds and Paper Digest full-text inputs.

The first production scope is publications from 2016 onward, matching the
existing ten-year corpus. Older records remain in the pinned raw snapshot and
can be enabled later without changing the identity or matching contracts.

The three outputs must remain distinct:

1. **Retrieval superset**: every Work matching at least one of the 85 raw terms.
2. **Finance-reviewed corpus**: retrieval rows passing finance-domain guards.
3. **Seed corpus**: reviewed rows satisfying graph and/or full-text eligibility.

A broad term such as `machine learning`, `intraday`, or `market order` must not
be silently discarded. It remains in the retrieval superset with evidence and
may be marked `review` or `rejected` by the domain screen.

## 2. Current verified baseline

- OpenAlex Works Parquet snapshot: `2026-06-26`.
- Works: 510,372,821 records in 2,446 files.
- Compressed size: 724,970,323,127 bytes.
- The Slurm probe successfully downloaded and read one file: 2,439 Works.
- The real Parquet schema contains title, DOI, IDs, authorships, topics,
  keywords, locations, primary/best OA locations, references, citation count,
  and an abstract inverted index stored as a JSON string.
- The source list contains 85 raw terms. After treating underscore and hyphen
  variants as aliases, there are 79 canonical phrases and six alias groups.
- Existing local inputs are useful for regression tests, not as the new global
  answer:
  - 4,214 arXiv→OpenAlex rows and 1,200 arXiv-only rows in Paper Digest.
  - 5,561 locally merged post-2016 arXiv rows.
  - 8,732 broad historical `factor` candidates, many unrelated to finance.
  - 1,797 manually-review-oriented OpenAlex match rows.
  - 2,090 previously accepted topic candidates; this set includes clear domain
    false positives and must not be treated as the 85-keyword corpus.

## 3. Canonical keyword contract

Copy the exact source terms into a versioned Paper Graph configuration. Every
run records the source checksum and matching version.

Normalization for matching:

1. Unicode NFKC normalization.
2. Case folding.
3. Replace `_` and hyphen variants with a space.
4. Collapse whitespace.
5. Match phrase/token boundaries rather than arbitrary substrings.
6. Preserve both the raw term and canonical alias group in output.

Search fields and ranking weights:

| Field | Retrieval | Ranking weight |
|---|---:|---:|
| title / display name | yes | 4 |
| OpenAlex keywords | yes | 3 |
| primary topic and topics | yes | 2 |
| reconstructed abstract | yes | 1 |

`retrieval_match = any field hit`. The weighted score ranks and audits results;
it does not define the initial retrieval universe.

Each match stores `matched_raw_terms`, `matched_canonical_terms`, per-field
hits, score, match version, and source snapshot date.

## 4. Snapshot acquisition and processing

### Phase A — pin and validate

1. Pin the Works Parquet manifest to snapshot date `2026-06-26`.
2. Store the manifest beside downloaded shards.
3. Verify every shard against manifest `content_length`.
4. Refuse to mix a changed manifest into the pinned directory.
5. Run all full synchronization and extraction jobs through Slurm.

The connectivity/schema probe has passed. Before the full run, add a
stratified pilot that samples old, middle, and recent `updated_date` partitions;
the first manifest shard alone is not representative.

### Phase B — shard extraction

Process each Parquet shard independently and checkpoint by object URL. Project
only fields needed downstream; do not convert the complete snapshot to JSONL.

Required projected fields:

- `openalex_id`, `title`, `display_name`
- `doi`, `ids`
- `publication_year`, `publication_date`, `type`, `language`
- normalized authors plus OpenAlex author IDs and ORCIDs
- primary topic, topics, keywords and concepts
- reconstructed abstract
- primary/best OA location and all repository locations
- `referenced_works`, `referenced_works_count`, `cited_by_count`
- `is_retracted`, `is_paratext`, `is_xpac`, OA/full-text flags
- `created_date`, `updated_date`, snapshot date

Outputs are partitioned Parquet, not one large JSONL:

- `openalex_quant_retrieval_v1/`
- `openalex_identity_v1/`
- `openalex_quant_audit_v1/`
- `openalex_extract_checkpoints_v1.json`

### Phase C — finance-domain audit

Apply a second, separately versioned screen. Strong evidence includes q-fin or
financial/econometrics topics and phrases such as trading, liquidity, price
impact, volatility, order book, execution, return, asset, portfolio, option,
or financial market. Generic-only matches such as `machine learning` require a
finance anchor in title/topic/abstract.

Statuses:

- `accepted`: keyword evidence plus finance anchor.
- `review`: ambiguous generic term or conflicting evidence.
- `rejected`: clear non-finance context.

No row is deleted; decisions and reasons remain auditable.

## 5. Identity model and arXiv recovery

OpenAlex ID is mandatory and remains the snapshot record identity. Canonical
paper identity is resolved using exact evidence in this order:

1. `ids.arxiv`, when present.
2. `locations[].id`, especially `pmh:oai:arXiv.org:<id>`.
3. arXiv landing-page and PDF URLs in primary, best-OA, or all locations.
4. canonical DOI `10.48550/arXiv.<id>`.
5. DOI for non-arXiv papers.

`indexed_in = arxiv` is only a presence hint and cannot produce an arXiv ID.
Title matching never creates an exact identity; it may create a manual-review
candidate only.

Identity output fields:

- `canonical_paper_id`
- `openalex_id`
- `arxiv_id`, optional version
- normalized DOI
- `identity_method`, `identity_evidence`, `identity_confidence`
- duplicate/representative status
- location source ID and snapshot date

Deduplication rules:

1. Merge exact same canonical arXiv ID.
2. Otherwise merge exact normalized DOI.
3. Keep same-title/author/year records separate unless manually reviewed.
4. Choose a representative OpenAlex Work by identity completeness, non-retracted
   status, publication version, metadata completeness, and citation count.

## 6. Seed eligibility

Two eligibility flags are required because graph construction and full-text
parsing have different requirements.

### `graph_seed_eligible`

Required:

- accepted finance status;
- stable OpenAlex ID and non-empty title;
- not retracted, not paratext, not XPAC;
- at least one explicit reference or one inbound citation found in snapshot;
- publication year in configured scope.

An arXiv ID is helpful but not mandatory for a structural graph seed.

### `digest_seed_eligible`

Required:

- `graph_seed_eligible` or explicitly approved review status;
- exact arXiv ID with retrievable TeX/PDF, or another verified full-text source
  supported by Paper Digest;
- title/identity consistency check passes;
- not already successfully parsed at the same content version.

OpenAlex-only papers can be graph nodes but must not enter the arXiv TeX queue.

## 7. Seed-graph feasibility pilot

Select an initial 30-paper stratified pilot:

- cover high-, medium-, and low-frequency keyword groups;
- cover recent and older publication years;
- include at least 20 exact arXiv identities;
- avoid selecting multiple duplicate versions of the same paper;
- prefer records with references and nontrivial citation counts.

For all 30 seeds in one snapshot scan:

1. Read each seed's outgoing `referenced_works`.
2. Find inbound citations by testing which Works reference any seed ID.
3. Select a bounded one-hop neighborhood per seed.
4. Resolve neighbor metadata from the local snapshot.
5. Build explicit `CITES` edges.
6. Compute bibliographic coupling/co-citation only from explicit references.
7. Do not launch a new embedding-generation job. Reuse existing embeddings
   only when available; otherwise the pilot remains structural.
8. Keep externally discovered nodes as `related`, never auto-promote them to
   seeds.

Pilot graph limits:

- one seed per diagnostic graph first;
- at most 40 nodes per graph;
- at most 20 inbound and 20 outbound candidates before ranking;
- retain excluded-node reasons and all edge provenance.

Success criteria:

- at least 90% of selected seeds produce a non-empty explicit citation graph;
- zero inferred citation edges without reference evidence;
- exact seed identity preserved through graph serialization;
- neighborhood construction is reproducible from snapshot and config hashes;
- false-positive review on a balanced sample is acceptable before scaling.

## 8. Paper Digest pilot

For the exact-arXiv subset of successful graph seeds:

1. Generate a dry-run Digest queue with title, arXiv ID, OpenAlex ID, keyword
   evidence, graph ID, and priority.
2. Verify arXiv identity/title before source retrieval.
3. Process a small first batch through the existing three-stage pipeline.
4. Preserve structured claims, evidence spans, methods, datasets, results,
   limitations, and citation context rather than flattening them to strings.
5. Attach parsed evidence back to the canonical paper and graph seed.

The first pilot should stop after a small successful batch. Full Digest parsing
and any LLM run must be submitted separately through Slurm after validating the
queue and startup path.

Digest success criteria:

- source retrieval succeeds for at least 80% of exact-arXiv pilot seeds;
- parsed title/arXiv identity remains consistent;
- claim/evidence objects retain source section/page or TeX anchors;
- graph seed can link to its parsed evidence record without title matching.

## 9. Required implementation changes

1. Version the exact 85-term list inside Paper Graph.
2. Update snapshot abstract reconstruction to parse the Parquet JSON-string
   representation as well as API dictionaries.
3. Implement a DuckDB shard extractor with checkpointed Parquet outputs.
4. Apply the shared arXiv resolver to snapshot and API records.
5. Replace the retired `ids.arxiv` filter in the old parsed-manifest matcher.
6. Add local snapshot neighborhood lookup so seed building no longer requires
   per-paper OpenAlex API calls.
7. Add a structural-only graph mode to prevent accidental new embeddings.
8. Generate separate graph-eligible and digest-eligible seed manifests.
9. Add regression tests using known arXiv-location examples and known
   non-finance false positives.

## 10. Execution gates

1. **Gate 1 — schema:** passed by the one-file probe.
2. **Gate 2 — stratified extraction:** validate counts, keyword evidence,
   arXiv coverage, and false positives on representative shards.
3. **Gate 3 — full snapshot:** submit complete manifest-pinned download and
   shard extraction through Slurm.
4. **Gate 4 — identity audit:** inspect duplicates and arXiv recovery rates.
5. **Gate 5 — 30-seed structural pilot:** require reproducible citation graphs.
6. **Gate 6 — small Digest pilot:** exact-arXiv seeds only.
7. **Gate 7 — scale:** build the balanced production seed pool and parse queue.

No full-scale graph, embedding, source-download, or LLM job should bypass its
preceding gate.
