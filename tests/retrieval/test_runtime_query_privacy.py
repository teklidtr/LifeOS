from __future__ import annotations

from pathlib import Path

import pytest

import lifeos.retrieval.service as base_service
from lifeos.retrieval import (
    HybridRetriever,
    RetrievalIndex,
    RetrievalIndexService,
    RetrievalRequest,
    chunk_markdown_file,
)
from lifeos.vault import read_vault_markdown


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_hybrid_retriever_health_uses_coherent_runtime_filtered_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / "runtime" / "node-a"
    _write(vault, "wiki/canonical.md", "# Canonical\n\ncanonical-health-marker\n")
    _write(
        vault,
        "runtime/node-a/derived.md",
        "---\ntitle: [\n---\nderived runtime content that must never be opened\n",
    )

    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()
    retriever = HybridRetriever(vault_root=vault, runtime_dir=runtime)

    reads: list[str] = []

    def recording_read(root: Path, relative_path: str):
        reads.append(relative_path)
        assert not relative_path.startswith("runtime/node-a/")
        return read_vault_markdown(root, relative_path)

    monkeypatch.setattr(base_service, "read_vault_markdown", recording_read)

    response = retriever.search(RetrievalRequest("canonical-health-marker"))

    assert response.results
    assert response.results[0].path == "wiki/canonical.md"
    assert reads == ["wiki/canonical.md"]


def test_hybrid_retriever_filters_stale_runtime_rows_at_query_time(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / "runtime" / "node-a"
    runtime_marker = "runtime-stale-secret-marker"
    _write(vault, "wiki/canonical.md", "# Canonical\n\ncanonical-only-marker\n")
    _write(
        vault,
        "runtime/node-a/derived.md",
        f"# Derived\n\n{runtime_marker}\n",
    )

    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()

    runtime_source = read_vault_markdown(vault, "runtime/node-a/derived.md")
    with RetrievalIndex(service.active_path, create=False) as index:
        index.replace_note(chunk_markdown_file(runtime_source))

    retriever = HybridRetriever(vault_root=vault, runtime_dir=runtime)
    response = retriever.search(RetrievalRequest(runtime_marker))

    assert response.index_state == "stale"
    assert all(not item.path.startswith("runtime/node-a/") for item in response.results)
    assert all(runtime_marker not in item.text for item in response.results)
