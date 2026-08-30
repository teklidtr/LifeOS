import json
from pathlib import Path

import pytest

import lifeos.facade.multi_source_ingestion as batch_module
from lifeos.facade.errors import ToolConflictError
from lifeos.facade.models import ToolEffect
from lifeos.facade.multi_source_ingestion import (
    EVOLVE_WIKI_BATCH_PROPOSAL_DESCRIPTOR,
    BatchWikiCreateRequest,
    EvolveWikiBatchProposalRequest,
    evolve_wiki_batch_proposal,
)
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


def test_batch_descriptor_is_proposal_producing() -> None:
    assert EVOLVE_WIKI_BATCH_PROPOSAL_DESCRIPTOR.name == "ingestion.evolve_wiki_batch_proposal"
    assert EVOLVE_WIKI_BATCH_PROPOSAL_DESCRIPTOR.effect == ToolEffect.PROPOSAL_PRODUCING


def test_batch_request_refuses_more_than_64_sources_without_fanout() -> None:
    with pytest.raises(ValueError, match="1..64 source paths"):
        EvolveWikiBatchProposalRequest(
            source_paths=tuple(f"notes/source-{index}.md" for index in range(65)),
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
            source_paths=("notes/source.md",),
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
        source_paths=sources,
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
