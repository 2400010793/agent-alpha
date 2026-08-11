from pathlib import Path

import duckdb

from paper_graph.snapshot_query import OpenAlexSnapshotQuery


def make_snapshot(path: Path) -> None:
    connection = duckdb.connect()
    connection.execute("""
        CREATE TABLE works AS SELECT * FROM (VALUES
            ('https://openalex.org/W1', 'Seed paper', '10.1000/seed', 2020,
             ['https://openalex.org/W2']::VARCHAR[], 1, 10),
            ('https://openalex.org/W2', 'Prior work', '10.1000/prior', 2018,
             []::VARCHAR[], 0, 100),
            ('https://openalex.org/W3', 'Derivative seed study', NULL, 2022,
             ['https://openalex.org/W1']::VARCHAR[], 1, 4)
        ) AS rows(id, title, doi, publication_year, referenced_works,
                  referenced_works_count, cited_by_count)
    """)
    connection.execute("COPY works TO ? (FORMAT PARQUET)", [str(path)])
    connection.close()


def test_queries_exact_local_seed_neighborhood(tmp_path: Path) -> None:
    path = tmp_path / "works.parquet"
    make_snapshot(path)
    with OpenAlexSnapshotQuery(path) as query:
        assert query.count() == 3
        assert query.work("W1")["title"] == "Seed paper"
        assert [row["id"] for row in query.outbound_references("W1")] == ["https://openalex.org/W2"]
        assert [row["id"] for row in query.inbound_citations("W1")] == ["https://openalex.org/W3"]
        neighborhood = query.seed_neighborhood("openalex:W1")
        assert neighborhood["stats"]["outbound_count"] == 1
        assert neighborhood["stats"]["inbound_count"] == 1


def test_searches_title_with_year_boundary(tmp_path: Path) -> None:
    path = tmp_path / "works.parquet"
    make_snapshot(path)
    with OpenAlexSnapshotQuery(path) as query:
        assert [row["id"] for row in query.search_title("seed", min_year=2021)] == [
            "https://openalex.org/W3"
        ]