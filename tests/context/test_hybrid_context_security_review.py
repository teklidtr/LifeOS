from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import lifeos.context.search as context_search
import lifeos.scanner as scanner
from lifeos.context import build_context_pack
from lifeos.retrieval import (
    CancellationToken,
    EmbeddingBatch,
    ProviderCapabilities,
    RetrievalIndexService,
    RetrievalScope,
)


def _write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class _RecordingEmbeddingProvider:
    def __init__(self, *, empty: bool = False) -> None:
        self.calls = 0
        self.empty = empty
        self._capabilities = ProviderCapabilities(
            kind="embedding",
            adapter_key="context-security-review",
            model_key="fixture-v1",
            local_only=True,
            max_batch_size=256,
            vector_dimensions=4,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None,
        cancellation: CancellationToken,
    ) -> EmbeddingBatch:
        del timeout_seconds
        cancellation.checkpoint()
        self.calls += 1
        if self.empty:
            return EmbeddingBatch((), self._capabilities)
        return EmbeddingBatch(
            tuple((1.0, 0.0, 0.0, 0.0) for _ in texts),
            self._capabilities,
        )


def test_protected_scope_ancestor_is_denied_before_directory_traversal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "private/secret.md", "---\ntitle: Secret\n---\nATP private evidence.")
    _write(vault, "wiki/public.md", "---\ntitle: Public\n---\nATP public evidence.")

    observed: dict[str, bool] = {}
    original = context_search.iter_vault_markdown_paths

    def recording_paths(root: Path, *, path_filter=None):
        assert path_filter is not None
        observed["private"] = path_filter("private")
        return original(root, path_filter=path_filter)

    monkeypatch.setattr(context_search, "iter_vault_markdown_paths", recording_paths)

    pack = build_context_pack(
        vault_root=vault,
        question="ATP evidence",
        retrieval_scope=RetrievalScope(paths=("private/secret.md",)),
    )

    assert observed["private"] is False
    assert not pack.sources


def test_leaf_only_caller_filter_reaches_nested_note_without_reading_rejected_leaf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/topic/allowed.md", "---\ntitle: Allowed\n---\nATP allowed evidence.")
    _write(vault, "wiki/topic/denied.md", "---\ntitle: Denied\n---\nATP denied evidence.")

    original_read = context_search.read_vault_markdown

    def guarded_read(root: Path, relative: str):
        if relative == "wiki/topic/denied.md":
            raise AssertionError("rejected caller-filter leaf was read")
        return original_read(root, relative)

    monkeypatch.setattr(context_search, "read_vault_markdown", guarded_read)

    pack = build_context_pack(
        vault_root=vault,
        question="ATP evidence",
        path_filter=lambda path: path == "wiki/topic/allowed.md",
    )

    assert [source.path for source in pack.sources] == ["wiki/topic/allowed.md"]
    assert pack.sources[0].retrieval_mode == "lexical-fallback"


def test_context_pack_computes_query_embedding_once_for_note_distinct_collection(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    long_body = "\n\n".join(
        f"ATP evidence paragraph {index}. " + ("ATP repeated evidence. " * 80)
        for index in range(30)
    )
    _write(vault, "wiki/long.md", f"---\ntitle: Long\n---\n{long_body}")
    _write(vault, "wiki/short.md", "---\ntitle: Short\n---\nATP separate evidence.")

    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()
    index_provider = _RecordingEmbeddingProvider()
    service.embed_missing(index_provider)
    query_provider = _RecordingEmbeddingProvider()

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP evidence",
        limit=2,
        embedding_provider=query_provider,
    )

    assert query_provider.calls == 1
    assert {source.path for source in pack.sources} == {"wiki/long.md", "wiki/short.md"}


def test_empty_query_embedding_batch_degrades_without_aborting_context(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(vault, "wiki/energy.md", "---\ntitle: Energy\n---\nATP energy evidence.")

    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()
    service.embed_missing(_RecordingEmbeddingProvider())
    empty_provider = _RecordingEmbeddingProvider(empty=True)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP energy",
        embedding_provider=empty_provider,
    )

    assert [source.path for source in pack.sources] == ["wiki/energy.md"]
    assert empty_provider.calls == 1
    assert any("malformed_provider_output" in item for item in pack.omissions)


def test_focus_duplicate_passage_does_not_consume_second_source_slot(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    shared = "ATP duplicate passage with the same canonical evidence."
    _write(vault, "study/focus.md", f"---\ntitle: Focus\n---\n{shared}")
    _write(vault, "wiki/duplicate.md", f"---\ntitle: Duplicate\n---\n{shared}")
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP duplicate passage",
        focus_paths=("study/focus.md",),
        limit=2,
    )

    assert [source.path for source in pack.sources] == ["study/focus.md"]


def test_description_routing_candidate_is_ranked_before_final_truncation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(
        vault,
        "wiki/routing.md",
        "---\ntitle: Routing\ndescription: mitochondrial ATP routing target\n---\n"
        "Unrelated canonical body.",
    )
    _write(
        vault,
        "wiki/body.md",
        "---\ntitle: Body\n---\nATP appears once in a low-value body match.",
    )
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="mitochondrial ATP",
        limit=1,
    )

    assert [source.path for source in pack.sources] == ["wiki/routing.md"]
    assert pack.sources[0].retrieval_mode == "lexical"


def test_hybrid_health_prunes_protected_subtree_before_metadata_access(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    vault.mkdir()
    _write(vault, "wiki/public.md", "---\ntitle: Public\n---\nATP public evidence.")
    RetrievalIndexService(vault_root=vault, runtime_dir=runtime).rebuild()

    # Add protected canonical state after the index snapshot. Health must prune the subtree before
    # child symlink/stat checks rather than enumerate it and filter the resulting path afterward.
    _write(vault, "private/secret.md", "---\ntitle: Secret\n---\nATP private evidence.")
    original_is_symlink = scanner.Path.is_symlink

    def guarded_is_symlink(path: Path) -> bool:
        try:
            relative = path.relative_to(vault).as_posix()
        except ValueError:
            return original_is_symlink(path)
        if relative == "private" or relative.startswith("private/"):
            raise AssertionError("protected subtree metadata was accessed during retrieval health")
        return original_is_symlink(path)

    monkeypatch.setattr(scanner.Path, "is_symlink", guarded_is_symlink)

    pack = build_context_pack(
        vault_root=vault,
        runtime_dir=runtime,
        question="ATP public",
    )

    assert [source.path for source in pack.sources] == ["wiki/public.md"]
