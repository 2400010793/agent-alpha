---
name: memory_absorption
description: Absorb external research text into structured memory for high-frequency alpha research.
---

# memory_absorption

This skill receives document chunks created by another crawler/reader.

Rules:

- Do not crawl or download documents.
- Mark each chunk as KEEP only if its mechanism can be represented by high-frequency whitelist fields.
- Mark chunks requiring fundamentals, news, macro, analyst data, or private data as DROP.
- Output RMA records and optional archetype memory.