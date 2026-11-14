"""Store and search vectors using PostgreSQL + pgvector (exact cosine search)."""
import json
from typing import Any

import psycopg

from .models import Chunk

FILTERABLE = {"document_id": "document_id", "year": "year", "chapter": "chapter", "article": "article"}


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vector) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int, table: str = "law_chunks") -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.database_url = database_url
        self.dimensions = dimensions
        self.table = table

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    strategy      text    NOT NULL,
                    chunk_id      text    NOT NULL,
                    document_id   text    NOT NULL,
                    source        text    NOT NULL,
                    page          integer NOT NULL,
                    year          integer,
                    chapter       text,
                    article       integer,
                    content_hash  text    NOT NULL,
                    text          text    NOT NULL,
                    metadata      jsonb   NOT NULL,
                    embedding     vector({self.dimensions}) NOT NULL,
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            conn.execute(f"CREATE INDEX IF NOT EXISTS {self.table}_filter_idx "
                         f"ON {self.table} (strategy, document_id, year)")

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> dict[str, int]:
        """Insert or update by (strategy, chunk_id) and drop stale chunks of re-ingested documents."""
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        if any(len(v) != self.dimensions for v in vectors):
            raise ValueError(f"every vector must have {self.dimensions} dimensions")
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate chunk_id in batch")
        documents = sorted({c.document_id for c in chunks})
        rows = [
            (strategy, c.chunk_id, c.document_id, c.source, c.page, c.metadata.get("year"),
             c.metadata.get("chapter"), c.metadata.get("article"), c.metadata["content_hash"],
             c.text, json.dumps(c.metadata, ensure_ascii=False), _vector_literal(v))
            for c, v in zip(chunks, vectors)
        ]
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(f"""
                    INSERT INTO {self.table} (strategy, chunk_id, document_id, source, page, year,
                        chapter, article, content_hash, text, metadata, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                    ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                        document_id = EXCLUDED.document_id, source = EXCLUDED.source,
                        page = EXCLUDED.page, year = EXCLUDED.year, chapter = EXCLUDED.chapter,
                        article = EXCLUDED.article, content_hash = EXCLUDED.content_hash,
                        text = EXCLUDED.text, metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding""", rows)
                cur.execute(
                    f"DELETE FROM {self.table} WHERE strategy = %s AND document_id = ANY(%s) "
                    f"AND NOT (chunk_id = ANY(%s))", (strategy, documents, ids))
                stale = cur.rowcount
        return {"upserted": len(rows), "stale_deleted": stale}

    def count(self, strategy: str) -> int:
        with self._connect() as conn:
            return conn.execute(f"SELECT count(*) FROM {self.table} WHERE strategy = %s",
                                (strategy,)).fetchone()[0]

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Filter on whitelisted metadata columns in SQL, then rank by cosine distance."""
        if len(query_vector) != self.dimensions:
            raise ValueError(f"query vector must have {self.dimensions} dimensions")
        clauses, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTERABLE:
                raise ValueError(f"filter on '{key}' is not allowed")
            clauses.append(f"{FILTERABLE[key]} = %s")
            params.append(value)
        vector = _vector_literal(query_vector)
        sql = (f"SELECT chunk_id, document_id, source, page, year, chapter, article, text, metadata, "
               f"1 - (embedding <=> %s::vector) AS score FROM {self.table} "
               f"WHERE {' AND '.join(clauses)} ORDER BY embedding <=> %s::vector LIMIT %s")
        with self._connect() as conn:
            rows = conn.execute(sql, [vector, *params, vector, top_k]).fetchall()
        return [
            {"chunk_id": r[0], "document_id": r[1], "source": r[2], "page": r[3], "year": r[4],
             "chapter": r[5], "article": r[6], "text": r[7],
             "metadata": {k: v for k, v in r[8].items() if k in ("law_title", "law_number",
                          "effective_date", "gazette_page", "article_title", "articles")},
             "score": round(float(r[9]), 4)}
            for r in rows
        ]
