"""Build a graph from local inputs only.

This placeholder deliberately does not call arXiv, OpenAlex, Semantic Scholar,
or any other external service.
"""

from paper_graph.pipeline import build_edges


def main() -> None:
    edges = build_edges([])
    print(f"paper graph is ready; generated {len(edges)} edges from local input")


if __name__ == "__main__":
    main()