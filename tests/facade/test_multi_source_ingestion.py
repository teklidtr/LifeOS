import hashlib
import json
from pathlib import Path

import pytest

import lifeos.facade.multi_source_ingestion as batch_module
from lifeos.facade.errors import ToolConflictError, ToolValidationError
from lifeos.facade.models import ToolEffect
from lifeos.facade.multi_source_ingestion import (
    EVOLVE_WIKI_BATCH_PROPOSAL_DESCRIPTOR,
    BatchSourceSnapshotRequest,
    BatchWikiCreateRequest,
    BatchWikiSectionRequest,
    BatchWikiUpdateRequest,
    EvolveWikiBatchProposalRequest,
    evolve_wiki_batch_proposal,
)
from lifeos.ingestion.multi_source import MAX_MULTI_SOURCE_PAYLOAD_BYTES
from lifeos.registry import Registry
from lifeos.registry.file_tracking import register_scan
from lifeos.scanner import VaultFile


def _write_ownership(vault_root: Path) -> None:
    system = vault_root / "system"
    system.mkdir(parents=True, exist_ok=True)
    (system / "generated-ownership.json").write_text(
        json.dumps({"schema_version": 1, "owned_files": {}}, sort_keys=True),
        encoding="utf-8",
    )


def _register_sources(vault_root: Path, tmp_path: Path, paths: tuple[str, ...]) -> Registry:
    entries: list[VaultFile] = []
    for index, relative in enumerate(paths, start=1):
        source = vault_root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"Source {index}.\n", encoding="utf-8")
        entries.append(VaultFile(Path(relative), ".md", source.stat().st_size))
    registry = Registry(tmp_path / "multi-source-registry.db")
    registry.initialize()
    register_scan(registry, vault_root, entries)
    return registry


def _observed_snapshots(
    vault_root: Path, paths: tuple[str, ...]
) -> tuple[BatchSourceSnapshotRequest, ...]:
    return tuple(
        BatchSourceSnapshotRequest(
            path=path,
            content_hash=f"sha256:{hashlib.sha256((vault_root / path).read_bytes()).hexdigest()}",
        )
        for path in paths
    )


def test_batch_descriptor_is_proposal_producing() -> None:
    assert EVOLVE_WIKI_BATCH_PROPOSAL_DESCRIPTOR.name == "ingestion.evolve_wiki_batch_proposal"
    assert EVOLVE_WIKI_BATCH_PROPOSAL_DESCRIPTOR.effect == ToolEffect.PROPOSAL_PRODUCING


def test_batch_request_refuses_more_than_64_sources_without_fanout() -> None:
    with pytest.raises(ValueError, match="1..64 source snapshots"):
        EvolveWikiBatchProposalRequest(
            source_snapshots=tuple(
                BatchSourceSnapshotRequest(
                    path=f"notes/source-{index}.md",
                    content_hash=f"sha256:{index:064x}",
                )
                for index in range(65)
            ),
            creates=(
                BatchWikiCreateRequest(
                    target_path="wiki/result.md",
                    title="Result",
                    body="Body",
                    rationale="Reconcile the batch.",
                    source_paths=("notes/source-0.md",),
                ),
            ),
        )


def test_batch_request_refuses_more_than_32_targets_without_fanout() -> None:
    with pytest.raises(ValueError, match="1..32 targets"):
        EvolveWikiBatchProposalRequest(
            source_snapshots=(
                BatchSourceSnapshotRequest(
                    path="notes/source.md",
                    content_hash="sha256:" + "1" * 64,
                ),
            ),
            creates=tuple(
                BatchWikiCreateRequest(
                    target_path=f"wiki/result-{index}.md",
                    title=f"Result {index}",
                    body="Body",
                    rationale="Reconcile one target.",
                    source_paths=("notes/source.md",),
                )
                for index in range(33)
            ),
        )


def test_exploration_time_source_hash_mismatch_aborts_before_draft(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "wiki").mkdir()
    (vault_root / "proposals").mkdir()
    _write_ownership(vault_root)
    sources = ("notes/source.md",)
    registry = _register_sources(vault_root, tmp_path, sources)
    observed = _observed_snapshots(vault_root, sources)

    source = vault_root / sources[0]
    source.write_text("Changed after the agent read the old version.\n", encoding="utf-8")
    register_scan(
        registry,
        vault_root,
        [VaultFile(Path(sources[0]), ".md", source.stat().st_size)],
    )
    request = EvolveWikiBatchProposalRequest(
        source_snapshots=observed,
        creates=(
            BatchWikiCreateRequest(
                target_path="wiki/result.md",
                title="Result",
                body="Candidate synthesized from the old source bytes.",
                rationale="Exercise exploration-time evidence binding.",
                source_paths=sources,
            ),
        ),
    )

    with pytest.raises(ToolConflictError, match="version read during exploration"):
        evolve_wiki_batch_proposal(
            vault_root=vault_root,
            registry=registry,
            request=request,
        )

    assert list((vault_root / "proposals").iterdir()) == []


def test_source_change_before_publication_aborts_whole_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "wiki").mkdir()
    (vault_root / "proposals").mkdir()
    _write_ownership(vault_root)
    sources = ("notes/a.md", "notes/b.md")
    registry = _register_sources(vault_root, tmp_path, sources)
    request = EvolveWikiBatchProposalRequest(
        source_snapshots=_observed_snapshots(vault_root, sources),
        creates=(
            BatchWikiCreateRequest(
                target_path="wiki/result.md",
                title="Result",
                body="Jointly grounded result.",
                rationale="Both sources support this target.",
                source_paths=sources,
            ),
        ),
    )

    original_builder = batch_module.build_multi_source_wiki_proposal

    def mutate_after_build(**kwargs: object):
        documents = original_builder(**kwargs)  # type: ignore[arg-type]
        (vault_root / "notes" / "b.md").write_text("Changed after first verification.\n")
        return documents

    monkeypatch.setattr(batch_module, "build_multi_source_wiki_proposal", mutate_after_build)

    with pytest.raises(ToolConflictError, match="Registered source has changed"):
        evolve_wiki_batch_proposal(
            vault_root=vault_root,
            registry=registry,
            request=request,
        )

    assert list((vault_root / "proposals").iterdir()) == []


def test_source_change_after_identity_binding_aborts_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "wiki").mkdir()
    (vault_root / "proposals").mkdir()
    _write_ownership(vault_root)
    sources = ("notes/source.md",)
    registry = _register_sources(vault_root, tmp_path, sources)
    source = vault_root / sources[0]
    request = EvolveWikiBatchProposalRequest(
        source_snapshots=_observed_snapshots(vault_root, sources),
        creates=(
            BatchWikiCreateRequest(
                target_path="wiki/result.md",
                title="Result",
                body="Candidate from the observed source.",
                rationale="Exercise the final publication source check.",
                source_paths=sources,
            ),
        ),
    )
    original_persist = batch_module.persist_compounding_wiki_proposal

    def mutate_at_before_publish(**kwargs: object):
        before_publish = kwargs.get("before_publish")
        assert callable(before_publish)

        def mutate_then_verify() -> None:
            source.write_text("Changed during stable-identity binding.\n", encoding="utf-8")
            before_publish()

        kwargs["before_publish"] = mutate_then_verify
        return original_persist(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        batch_module, "persist_compounding_wiki_proposal", mutate_at_before_publish
    )

    with pytest.raises(ToolConflictError, match="Registered source has changed"):
        evolve_wiki_batch_proposal(
            vault_root=vault_root,
            registry=registry,
            request=request,
        )

    assert list((vault_root / "proposals").iterdir()) == []


def test_target_change_before_review_snapshot_maps_to_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "wiki").mkdir()
    (vault_root / "proposals").mkdir()
    _write_ownership(vault_root)
    sources = ("notes/source.md",)
    registry = _register_sources(vault_root, tmp_path, sources)
    target = vault_root / "wiki" / "topic.md"
    target.write_text("# Topic\n\n## Evidence\nold\n", encoding="utf-8")
    request = EvolveWikiBatchProposalRequest(
        source_snapshots=_observed_snapshots(vault_root, sources),
        updates=(
            BatchWikiUpdateRequest(
                target_path="wiki/topic.md",
                sections=(BatchWikiSectionRequest(heading="Evidence", body="new"),),
                rationale="Exercise stale review snapshot mapping.",
                source_paths=sources,
            ),
        ),
    )

    original_builder = batch_module.build_multi_source_wiki_proposal

    def mutate_target_after_build(**kwargs: object):
        documents = original_builder(**kwargs)  # type: ignore[arg-type]
        target.write_text("# Topic\n\n## Evidence\nchanged elsewhere\n", encoding="utf-8")
        return documents

    monkeypatch.setattr(batch_module, "build_multi_source_wiki_proposal", mutate_target_after_build)

    with pytest.raises(ToolConflictError, match="batch target changed"):
        evolve_wiki_batch_proposal(
            vault_root=vault_root,
            registry=registry,
            request=request,
        )

    assert list((vault_root / "proposals").iterdir()) == []


def test_stable_identity_binding_stale_target_maps_to_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "wiki").mkdir()
    (vault_root / "proposals").mkdir()
    _write_ownership(vault_root)
    sources = ("notes/source.md",)
    registry = _register_sources(vault_root, tmp_path, sources)
    target = vault_root / "wiki" / "topic.md"
    original = "---\nid: topic-stable\ntitle: Topic\n---\n# Topic\n\n## Evidence\nold\n"
    target.write_text(original, encoding="utf-8")
    request = EvolveWikiBatchProposalRequest(
        source_snapshots=_observed_snapshots(vault_root, sources),
        updates=(
            BatchWikiUpdateRequest(
                target_path="wiki/topic.md",
                sections=(BatchWikiSectionRequest(heading="Evidence", body="new"),),
                rationale="Exercise stable-identity stale target mapping.",
                source_paths=sources,
            ),
        ),
    )
    original_persist = batch_module.persist_compounding_wiki_proposal

    def mutate_before_identity_binding(**kwargs: object):
        target.write_text(
            "---\nid: topic-stable\ntitle: Topic\n---\n"
            "# Topic\n\n## Evidence\nchanged elsewhere\n",
            encoding="utf-8",
        )
        return original_persist(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        batch_module, "persist_compounding_wiki_proposal", mutate_before_identity_binding
    )

    with pytest.raises(ToolConflictError, match="batch target changed"):
        evolve_wiki_batch_proposal(
            vault_root=vault_root,
            registry=registry,
            request=request,
        )

    assert list((vault_root / "proposals").iterdir()) == []


def test_oversized_payload_fails_before_draft_persistence(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "wiki").mkdir()
    (vault_root / "proposals").mkdir()
    _write_ownership(vault_root)
    sources = ("notes/source.md",)
    registry = _register_sources(vault_root, tmp_path, sources)
    request = EvolveWikiBatchProposalRequest(
        source_snapshots=_observed_snapshots(vault_root, sources),
        creates=(
            BatchWikiCreateRequest(
                target_path="wiki/oversized.md",
                title="Oversized",
                body="x" * MAX_MULTI_SOURCE_PAYLOAD_BYTES,
                rationale="Exercise the publication payload boundary.",
                source_paths=sources,
            ),
        ),
    )

    with pytest.raises(ToolValidationError, match="patch/review payload exceeds"):
        evolve_wiki_batch_proposal(
            vault_root=vault_root,
            registry=registry,
            request=request,
        )

    assert list((vault_root / "proposals").iterdir()) == []
