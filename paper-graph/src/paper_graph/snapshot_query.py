"""Local DuckDB queries over manifest-pinned OpenAlex Works Parquet files."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import duckdb

from .identity import normalize_openalex_id


def _openalex_url(value: str) -> str:
    ident = normalize_openalex_id(value)
    if not ident:
        raise ValueError(f"invalid OpenAlex Work ID: {value}")
    return f"https://openalex.org/{ident}"


class OpenAlexSnapshotQuery:
    """Read a bounded Work neighborhood without per-paper API requests."""

    def __init__(self, files: str | Path | Iterable[str | Path], *, threads: int = 4) -> None:
        if isinstance(files, (str, Path)):
            path = Path(files)
            resolved = sorted(path.glob("updated_date=*/*.parquet")) if path.is_dir() else [path]
        else:
            resolved = [Path(path) for path in files]
        self.files = [str(path) for path in resolved if path.exists()]
        if not self.files:
            raise ValueError("no OpenAlex Parquet files found")
        self.connection = duckdb.connect()
        self.connection.execute(f"SET threads={max(1, int(threads))}")

    @staticmethod
    def _rows(cursor: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, values)) for values in cursor.fetchall()]

    def count(self, *, min_year: int | None = None) -> int:
        if min_year is None:
            return int(self.connection.execute(
                "SELECT count(*) FROM read_parquet(?)", [self.files]
            ).fetchone()[0])
        return int(self.connection.execute(
            "SELECT count(*) FROM read_parquet(?) WHERE publication_year >= ?",
            [self.files, min_year],
        ).fetchone()[0])

    def work(self, openalex_id: str) -> dict[str, Any] | None:
        rows = self._rows(self.connection.execute(
            "SELECT * FROM read_parquet(?) WHERE id = ? LIMIT 1",
            [self.files, _openalex_url(openalex_id)],
        ))
        return rows[0] if rows else None

    def search_title(self, query: str, *, limit: int = 20, min_year: int | None = None) -> list[dict[str, Any]]:
        text = str(query).strip()
        if not text or limit < 1:
            return []
        condition = "title ILIKE '%' || ? || '%'"
        parameters: list[Any] = [self.files, text]
        if min_year is not None:
            condition += " AND publication_year >= ?"
            parameters.append(min_year)
        parameters.append(limit)
        return self._rows(self.connection.execute(
            f"""SELECT * FROM read_parquet(?) WHERE {condition}
                ORDER BY cited_by_count DESC NULLS LAST, publication_year DESC NULLS LAST
                LIMIT ?""",
            parameters,
        ))

    def outbound_references(self, openalex_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        seed_url = _openalex_url(openalex_id)
        return self._rows(self.connection.execute(
            f"""WITH works AS (SELECT * FROM read_parquet(?)),
                       refs AS (
                           SELECT unnest(referenced_works) AS target_id
                           FROM works WHERE id = ?
                       )
                SELECT target.*
                FROM refs JOIN works target ON target.id = refs.target_id
                ORDER BY target.cited_by_count DESC NULLS LAST
                LIMIT ?""",
            [self.files, seed_url, limit],
        ))

    def inbound_citations(self, openalex_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        seed_url = _openalex_url(openalex_id)
        return self._rows(self.connection.execute(
            """SELECT * FROM read_parquet(?)
                WHERE list_contains(referenced_works, ?)
                ORDER BY cited_by_count DESC NULLS LAST
                LIMIT ?""",
            [self.files, seed_url, limit],
        ))

    def seed_neighborhood(self, openalex_id: str, *, per_direction: int = 20) -> dict[str, Any]:
        seed = self.work(openalex_id)
        if seed is None:
            raise KeyError(f"OpenAlex Work not found in local snapshot: {openalex_id}")
        outbound = self.outbound_references(openalex_id, limit=per_direction)
        inbound = self.inbound_citations(openalex_id, limit=per_direction)
        return {
            "seed": seed,
            "outbound_references": outbound,
            "inbound_citations": inbound,
            "stats": {
                "outbound_count": len(outbound),
                "inbound_count": len(inbound),
                "per_direction": per_direction,
                "source": "openalex_local_snapshot",
            },
        }

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "OpenAlexSnapshotQuery":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()