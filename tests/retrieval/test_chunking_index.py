from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.retrieval import (
    CancellationToken,
    DeterministicEmbeddingProvider,
    RetrievalError,
    RetrievalIndex,
    chunk_markdown_file,
    reidentify_note,
)
from lifeos.vault import VaultMarkdownFile


def source(tmp_path: Path, relative: str, content: str) -> VaultMarkdownFile:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return VaultMarkdownFile(relative, path, content, content.encode())


def test_heading_boundaries_block_ids_links_and_provenance(tmp_path: Path) -> None:
    note = chunk_markdown_file(
        source(
            tmp_path,
            "wiki/a.md",
            """---
id: note-a
type: concept
title: Energy Balance
tags: [biology, metabolism]
source: textbook
---
# Overview

Cells conserve usable energy. ^claim-one

See [[wiki/b#Details]].

## Limits

A conflicting account exists.
""",
        ),
        indexed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    assert note.document.document_id == "id:note-a"
    assert note.document.tags == ("biology", "metabolism")
    assert [chunk.heading for chunk in note.chunks] == ["Overview", "Overview", "Limits"]
    assert note.chunks[0].block_id == "claim-one"
    assert note.chunks[1].links == (("wiki/b.md", "Details"),)
    assert note.chunks[0].start_line > 7
    assert note.chunks[0].metadata["source"] == "textbook"


def test_false_fence_closer_does_not_create_retrieval_headings(
    tmp_path: Path,
) -> None:
    note = chunk_markdown_file(
        source(
            tmp_path,
            "wiki/fenced.md",
            "# Outside\n\n"
            "```md\n"
            "```not-a-closing-fence\n"
            "## Inside code\n"
            "example\n"
            "```\n\n"
            "## Real section\n\n"
            "Real text.\n",
        )
    )

    assert "Inside code" not in {chunk.heading for chunk in note.chunks}
    assert "Real section" in {chunk.heading for chunk in note.chunks}
    assert any("## Inside code" in chunk.text for chunk in note.chunks)


def test_structural_chunking_suppresses_duplicate_passages_and_bounds_large_notes(
    tmp_path: Path,
) -> None:
    repeated = "Repeated evidence paragraph."
    content = (
        "# A\n\n"
        + repeated
        + "\n\n"
        + repeated
        + "\n\n"
        + " ".join(f"Long sentence {index}." for index in range(300))
    )
    note = chunk_markdown_file(source(tmp_path, "wiki/large.md", content), max_chunk_characters=300)
    assert any(item.startswith("duplicate-passage") for item in note.diagnostics)
    assert len(note.chunks) > 2
    assert max(len(chunk.text) for chunk in note.chunks) <= 300


def test_malformed_frontmatter_and_unsupported_files_fail_safely(tmp_path: Path) -> None:
    with pytest.raises(RetrievalError) as malformed:
        chunk_markdown_file(source(tmp_path, "wiki/bad.md", "---\ntitle: [\n---\nBody"))
    assert malformed.value.code == "malformed_note"
    with pytest.raises(RetrievalError) as unsupported:
        chunk_markdown_file(source(tmp_path, "wiki/a.txt", "text"))
    assert unsupported.value.code == "unsupported_file"


def test_index_round_trip_links_and_fresh_embeddings(tmp_path: Path) -> None:
    note = chunk_markdown_file(
        source(tmp_path, "wiki/a.md", "# A\n\nAlpha [[b]].\n\n## B\n\nBeta.")
    )
    index_path = tmp_path / ".lifeos" / "retrieval" / "index.sqlite3"
    with RetrievalIndex(index_path) as index:
        index.replace_note(note)
        assert index.counts() == {"documents": 1, "chunks": 2, "links": 1, "embeddings": 0}
        assert index.document_by_path("wiki/a.md") == note.document
        assert index.chunks() == note.chunks
        provider = DeterministicEmbeddingProvider(dimensions=4)
        batch = provider.embed(
            [chunk.text for chunk in note.chunks],
            timeout_seconds=1,
            cancellation=CancellationToken(),
        )
        index.write_embeddings(chunks=note.chunks, batch=batch, created_at="2026-07-16T00:00:00Z")
        assert len(index.embeddings(provider.capabilities)) == 2
        assert index.stale_embedding_count() == 0


def test_replacing_changed_note_drops_orphan_chunks_and_embeddings(tmp_path: Path) -> None:
    first = chunk_markdown_file(source(tmp_path, "wiki/a.md", "# A\n\nAlpha.\n\n## B\n\nBeta."))
    index = RetrievalIndex(tmp_path / "index.sqlite3")
    index.replace_note(first)
    provider = DeterministicEmbeddingProvider(dimensions=4)
    index.write_embeddings(
        chunks=first.chunks,
        batch=provider.embed(
            [item.text for item in first.chunks],
            timeout_seconds=1,
            cancellation=CancellationToken(),
        ),
        created_at="now",
    )
    second = chunk_markdown_file(source(tmp_path, "wiki/a.md", "# A\n\nChanged."))
    index.replace_note(second)
    assert index.counts()["chunks"] == 1
    assert index.counts()["embeddings"] == 0
    index.close()


def test_reidentify_preserves_document_identity_for_rename(tmp_path: Path) -> None:
    note = chunk_markdown_file(source(tmp_path, "wiki/new.md", "# A\n\nText."))
    renamed = reidentify_note(note, "path:preserved")
    assert renamed.document.document_id == "path:preserved"
    assert all(chunk.document_id == "path:preserved" for chunk in renamed.chunks)
    assert renamed.chunks[0].chunk_id != note.chunks[0].chunk_id


def test_incompatible_schema_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "index.sqlite3"
    index = RetrievalIndex(path)
    index.set_meta("schema_version", "99")
    index.close()
    with pytest.raises(RetrievalError) as caught:
        RetrievalIndex(path)
    assert caught.value.code == "incompatible_index"
