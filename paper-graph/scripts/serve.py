"""Start the local Paper Graph API using the bundled demo dataset."""

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn

from paper_graph.api import create_app
from paper_graph.digest_adapter import load_digest_papers
from paper_graph.embeddings import HashEmbeddingEncoder, LocalSemanticIndex
from paper_graph.similarity import top_k_embedding_edges
from paper_graph.service import PaperGraphService
from paper_graph.storage import PaperStore


ROOT = Path(__file__).resolve().parents[1]
digest_root = Path("/home/gaozh/my-paper-digest-new2")
digest_papers = load_digest_papers(digest_root)
if digest_papers:
    embeddings = HashEmbeddingEncoder().encode_papers(digest_papers)
    digest_edges = top_k_embedding_edges(embeddings, k=16, minimum_score=0.05)
    store = PaperStore(digest_papers, digest_edges)
else:
    store = PaperStore.from_jsonl(
        ROOT / "data/processed/demo_papers.jsonl",
        ROOT / "data/processed/demo_edges.jsonl",
    )
local_semantic_search = None
if digest_papers and os.environ.get("PAPER_GRAPH_SPECTER2", "").lower() in {"1", "true", "yes"}:
    local_semantic_index = LocalSemanticIndex(digest_papers, threshold=0.75)
    local_semantic_search = local_semantic_index.search

topic_graph_root = ROOT / "docs/generated/digest-topic-graphs/three-ai-v2"
app = create_app(PaperGraphService(store), topic_graph_root=str(topic_graph_root),
                local_semantic_search=local_semantic_search)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.environ.get("PAPER_GRAPH_HOST", "0.0.0.0"),
        port=int(os.environ.get("PAPER_GRAPH_PORT", "8009")),
        reload=os.environ.get("PAPER_GRAPH_RELOAD", "").lower() in {"1", "true", "yes"},
    )