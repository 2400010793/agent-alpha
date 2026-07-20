---
name: paper_to_signal
description: Convert an existing reading note and evidence pack into high-frequency alpha signals. Do not crawl papers.
---

# paper_to_signal

Input must already contain a `reading_note_v1` object and evidence references from another crawler/reader.

Rules:

- Do not fetch papers, PDFs, web pages, or arXiv records.
- Do not generate factor code.
- Output only `AlphaSignal` records.
- Every signal must cite evidence ids from the reading note or evidence pack.
- Every signal must include high-frequency mechanism tags and candidate fields from the field whitelist.