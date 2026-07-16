"""Versioned disposable SQLite storage for structural retrieval data."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from lifeos.retrieval.contracts import EmbeddingBatch, ProviderCapabilities, RetrievalError
from lifeos.retrieval.models import ChunkedNote, IndexedChunk, IndexedDocument

INDEX_SCHEMA_VERSION = 1
INDEX_RELATIVE_PATH = Path("retrieval/index.sqlite3")

_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    note_type TEXT,
    source TEXT,
    note_date TEXT,
    tags_json TEXT NOT NULL,
    frontmatter_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS documents_hash_idx ON documents(content_hash);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    heading TEXT,
    heading_path_json TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    block_id TEXT,
    text TEXT NOT NULL,
    normalized_hash TEXT NOT NULL,
    chunk_hash TEXT NOT NULL,
    links_json TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks(document_id);
CREATE INDEX IF NOT EXISTS chunks_path_idx ON chunks(path);
CREATE INDEX IF NOT EXISTS chunks_normalized_idx ON chunks(normalized_hash);
CREATE TABLE IF NOT EXISTS links (
    from_chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    target_path TEXT NOT NULL,
    target_heading TEXT,
    PRIMARY KEY (from_chunk_id, target_path, target_heading)
);
CREATE INDEX IF NOT EXISTS links_target_idx ON links(target_path);
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    adapter_key TEXT NOT NULL,
    model_key TEXT NOT NULL,
    chunk_hash TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (chunk_id, adapter_key, model_key)
);
"""


@dataclass(frozen=True, slots=True)
class StoredEmbedding:
    chunk_id: str
    adapter_key: str
    model_key: str
    chunk_hash: str
    vector: tuple[float, ...]
    created_at: str
    stale: bool


class RetrievalIndex:
    def __init__(self, path: Path, *, create: bool = True) -> None:
        self.path = path
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        if not create and not path.exists():
            raise RetrievalError("missing_index", "The retrieval index does not exist.")
        try:
            self.connection = sqlite3.connect(path)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            if create:
                self.connection.executescript(_SCHEMA)
                self.connection.execute(
                    "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
                    (str(INDEX_SCHEMA_VERSION),),
                )
                self.connection.commit()
            self._validate_schema()
        except sqlite3.DatabaseError as exc:
            raise RetrievalError("corrupt_index", f"The retrieval index is unreadable: {exc}") from exc

    @classmethod
    def open_runtime(cls, runtime_dir: Path, *, create: bool = True) -> "RetrievalIndex":
        return cls(runtime_dir / INDEX_RELATIVE_PATH, create=create)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "RetrievalIndex":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def replace_note(self, note: ChunkedNote) -> None:
        with self.transaction():
            prior = self.connection.execute(
                "SELECT document_id FROM documents WHERE path = ?", (note.document.path,)
            ).fetchone()
            if prior is not None and prior["document_id"] != note.document.document_id:
                self.connection.execute("DELETE FROM documents WHERE document_id = ?", (prior["document_id"],))
            self.connection.execute("DELETE FROM documents WHERE document_id = ?", (note.document.document_id,))
            self._insert_document(note.document)
            for chunk in note.chunks:
                self._insert_chunk(chunk)

    def delete_path(self, path: str) -> int:
        with self.transaction():
            cursor = self.connection.execute("DELETE FROM documents WHERE path = ?", (path,))
        return cursor.rowcount

    def rename_path(self, old_path: str, note: ChunkedNote) -> None:
        with self.transaction():
            self.connection.execute("DELETE FROM documents WHERE path = ?", (old_path,))
            self.connection.execute("DELETE FROM documents WHERE document_id = ?", (note.document.document_id,))
            self._insert_document(note.document)
            for chunk in note.chunks:
                self._insert_chunk(chunk)

    def documents(self) -> tuple[IndexedDocument, ...]:
        rows = self.connection.execute("SELECT * FROM documents ORDER BY path").fetchall()
        return tuple(self._document(row) for row in rows)

    def document_by_path(self, path: str) -> IndexedDocument | None:
        row = self.connection.execute("SELECT * FROM documents WHERE path = ?", (path,)).fetchone()
        return self._document(row) if row else None

    def documents_by_hash(self, content_hash: str) -> tuple[IndexedDocument, ...]:
        rows = self.connection.execute(
            "SELECT * FROM documents WHERE content_hash = ? ORDER BY path", (content_hash,)
        ).fetchall()
        return tuple(self._document(row) for row in rows)

    def chunks(self, *, paths: Sequence[str] | None = None) -> tuple[IndexedChunk, ...]:
        if paths:
            placeholders = ",".join("?" for _ in paths)
            rows = self.connection.execute(
                f"SELECT * FROM chunks WHERE path IN ({placeholders}) ORDER BY path, start_line, chunk_id",
                tuple(paths),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM chunks ORDER BY path, start_line, chunk_id"
            ).fetchall()
        return tuple(self._chunk(row) for row in rows)

    def chunk(self, chunk_id: str) -> IndexedChunk | None:
        row = self.connection.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        return self._chunk(row) if row else None

    def write_embeddings(
        self,
        *,
        chunks: Sequence[IndexedChunk],
        batch: EmbeddingBatch,
        created_at: str,
    ) -> None:
        if len(chunks) != len(batch.vectors):
            raise RetrievalError("malformed_provider_output", "Provider returned the wrong embedding count.")
        capability = batch.capabilities
        if capability.kind != "embedding":
            raise RetrievalError("invalid_provider", "Only embedding capabilities can be stored.")
        with self.transaction():
            for chunk, vector in zip(chunks, batch.vectors, strict=True):
                self.connection.execute(
                    """INSERT INTO embeddings(chunk_id, adapter_key, model_key, chunk_hash, dimensions, vector_json, created_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(chunk_id, adapter_key, model_key) DO UPDATE SET
                         chunk_hash=excluded.chunk_hash, dimensions=excluded.dimensions,
                         vector_json=excluded.vector_json, created_at=excluded.created_at""",
                    (
                        chunk.chunk_id,
                        capability.adapter_key,
                        capability.model_key,
                        chunk.chunk_hash,
                        len(vector),
                        json.dumps(vector, separators=(",", ":"), allow_nan=False),
                        created_at,
                    ),
                )

    def embeddings(
        self, capabilities: ProviderCapabilities, *, include_stale: bool = False
    ) -> tuple[StoredEmbedding, ...]:
        rows = self.connection.execute(
            """SELECT e.*, c.chunk_hash AS current_chunk_hash
               FROM embeddings e JOIN chunks c ON c.chunk_id=e.chunk_id
               WHERE e.adapter_key=? AND e.model_key=? ORDER BY e.chunk_id""",
            (capabilities.adapter_key, capabilities.model_key),
        ).fetchall()
        values: list[StoredEmbedding] = []
        for row in rows:
            stale = row["chunk_hash"] != row["current_chunk_hash"]
            if stale and not include_stale:
                continue
            vector = tuple(float(value) for value in json.loads(row["vector_json"]))
            if len(vector) != row["dimensions"] or any(not math.isfinite(value) for value in vector):
                raise RetrievalError("corrupt_index", "Stored embedding is malformed.")
            values.append(
                StoredEmbedding(
                    row["chunk_id"], row["adapter_key"], row["model_key"],
                    row["chunk_hash"], vector, row["created_at"], stale,
                )
            )
        return tuple(values)

    def stale_embedding_count(self) -> int:
        row = self.connection.execute(
            """SELECT COUNT(*) AS count FROM embeddings e
               JOIN chunks c ON c.chunk_id=e.chunk_id WHERE e.chunk_hash != c.chunk_hash"""
        ).fetchone()
        return int(row["count"])

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in ("documents", "chunks", "links", "embeddings"):
            row = self.connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            result[table] = int(row["count"])
        return result

    def set_meta(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.connection.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def _validate_schema(self) -> None:
        try:
            row = self.connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        except sqlite3.DatabaseError as exc:
            raise RetrievalError("corrupt_index", "The retrieval index schema is missing.") from exc
        if row is None:
            raise RetrievalError("corrupt_index", "The retrieval index schema version is missing.")
        try:
            version = int(row["value"])
        except (TypeError, ValueError) as exc:
            raise RetrievalError("corrupt_index", "The retrieval index schema version is invalid.") from exc
        if version != INDEX_SCHEMA_VERSION:
            raise RetrievalError(
                "incompatible_index",
                "The retrieval index schema is incompatible.",
                {"expected": INDEX_SCHEMA_VERSION, "actual": version},
            )

    def _insert_document(self, item: IndexedDocument) -> None:
        self.connection.execute(
            """INSERT INTO documents(document_id,path,title,note_type,source,note_date,tags_json,frontmatter_json,content_hash,indexed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                item.document_id, item.path, item.title, item.note_type, item.source,
                item.note_date, json.dumps(item.tags, ensure_ascii=False),
                json.dumps(item.frontmatter, ensure_ascii=False, sort_keys=True),
                item.content_hash, item.indexed_at,
            ),
        )

    def _insert_chunk(self, item: IndexedChunk) -> None:
        self.connection.execute(
            """INSERT INTO chunks(chunk_id,document_id,path,heading,heading_path_json,start_line,end_line,block_id,text,normalized_hash,chunk_hash,links_json,token_count,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item.chunk_id, item.document_id, item.path, item.heading,
                json.dumps(item.heading_path, ensure_ascii=False), item.start_line,
                item.end_line, item.block_id, item.text, item.normalized_hash,
                item.chunk_hash, json.dumps(item.links, ensure_ascii=False),
                item.token_count, json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
            ),
        )
        for target_path, target_heading in item.links:
            self.connection.execute(
                "INSERT INTO links(from_chunk_id,target_path,target_heading) VALUES(?,?,?)",
                (item.chunk_id, target_path, target_heading or ""),
            )

    @staticmethod
    def _document(row: sqlite3.Row) -> IndexedDocument:
        return IndexedDocument(
            row["document_id"], row["path"], row["title"], row["note_type"], row["source"],
            row["note_date"], tuple(json.loads(row["tags_json"])), json.loads(row["frontmatter_json"]),
            row["content_hash"], row["indexed_at"],
        )

    @staticmethod
    def _chunk(row: sqlite3.Row) -> IndexedChunk:
        return IndexedChunk(
            row["chunk_id"], row["document_id"], row["path"], row["heading"],
            tuple(json.loads(row["heading_path_json"])), row["start_line"], row["end_line"],
            row["block_id"], row["text"], row["normalized_hash"], row["chunk_hash"],
            tuple(tuple(item) for item in json.loads(row["links_json"])), row["token_count"],
            json.loads(row["metadata_json"]),
        )
