"""Embedding interfaces, including optional local SPECTER2 retrieval."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping

from .text import build_embedding_text
from .similarity import cosine_similarity


class HashEmbeddingEncoder:
    """Deterministic dependency-free baseline encoder.

    It is useful for tests and local API development, not a scientific final
    model. Replace it with a paper embedding model behind the same interface.
    """

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions < 8:
            raise ValueError("dimensions must be at least 8")
        self.dimensions = dimensions

    def encode(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[\w-]+", text.casefold())
        for token in tokens:
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def encode_papers(self, papers: Iterable[Mapping[str, object]]) -> dict[str, list[float]]:
        result = {}
        for paper in papers:
            paper_id = str(paper["id"])
            text, _ = build_embedding_text(paper)
            result[paper_id] = self.encode(text)
        return result


class Specter2Encoder:
    """SPECTER2 encoder backed by ``transformers`` and the official adapter.

    The model is loaded lazily, so importing the API does not download a model.
    Install the optional ``semantic`` dependencies before enabling it.
    """

    def __init__(self, model_name: str = "allenai/specter2_base",
                 adapter_name: str = "allenai/specter2") -> None:
        self.model_name = model_name
        self.adapter_name = adapter_name
        self._model = None
        self._tokenizer = None

    def _load(self):
        if self._model is None:
            try:
                import torch
                from adapters import AutoAdapterModel
                from transformers import AutoTokenizer
            except ImportError as exc:
                raise RuntimeError("install paper-graph[semantic] to use SPECTER2") from exc
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoAdapterModel.from_pretrained(self.model_name)
            self._model.load_adapter(self.adapter_name, source="hf", load_as="specter2")
            self._model.set_active_adapters("specter2")
            self._model.eval()
            self._torch = torch
        return self._model, self._tokenizer

    def encode(self, text: str) -> list[float]:
        model, tokenizer = self._load()
        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        with self._torch.no_grad():
            output = model(**inputs).last_hidden_state[:, 0, :]
            output = output / output.norm(dim=1, keepdim=True).clamp_min(1e-12)
        return [float(value) for value in output[0].cpu().tolist()]

    def encode_papers(self, papers: Iterable[Mapping[str, object]]) -> dict[str, list[float]]:
        values = list(papers)
        texts = [build_embedding_text(paper)[0] for paper in values]
        vectors = [self.encode(text) for text in texts]
        return {str(paper["id"]): vector for paper, vector in zip(values, vectors)}


class LocalSemanticIndex:
    """In-memory vector index over the local PaperStore papers."""

    def __init__(self, papers: Iterable[Mapping[str, object]], encoder: Specter2Encoder | None = None,
                 threshold: float = 0.75) -> None:
        self.papers = {str(paper["id"]): dict(paper) for paper in papers}
        self.encoder = encoder or Specter2Encoder()
        self.threshold = threshold
        self._vectors: dict[str, list[float]] = {}

    def search(self, seed: Mapping[str, object], limit: int = 20) -> list[dict]:
        if not self.papers or limit < 1:
            return []
        seed_text, _ = build_embedding_text(seed)
        seed_vector = self.encoder.encode(seed_text)
        missing = [paper for paper_id, paper in self.papers.items() if paper_id not in self._vectors]
        if missing:
            self._vectors.update(self.encoder.encode_papers(missing))
        ranked = []
        seed_id = str(seed.get("id", ""))
        for paper_id, paper in self.papers.items():
            if paper_id == seed_id:
                continue
            score = cosine_similarity(seed_vector, self._vectors[paper_id])
            if score >= self.threshold:
                result = dict(paper)
                result["metadata"] = {**(paper.get("metadata") or {}),
                    "discovered_via": "local_specter2", "discovered_from": seed_id,
                    "embedding_model": self.encoder.model_name, "embedding_score": score}
                ranked.append((score, result))
        return [paper for _, paper in sorted(ranked, key=lambda item: -item[0])[:limit]]