"""Immutable structural index models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IndexedDocument:
    document_id: str
    path: str
    title: str
    note_type: str | None
    source: str | None
    note_date: str | None
    tags: tuple[str, ...]
    frontmatter: dict[str, Any]
    content_hash: str
    indexed_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IndexedChunk:
    chunk_id: str
    document_id: str
    path: str
    heading: str | None
    heading_path: tuple[str, ...]
    start_line: int
    end_line: int
    block_id: str | None
    text: str
    normalized_hash: str
    chunk_hash: str
    links: tuple[tuple[str, str | None], ...]
    token_count: int
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChunkedNote:
    document: IndexedDocument
    chunks: tuple[IndexedChunk, ...]
    diagnostics: tuple[str, ...] = ()
