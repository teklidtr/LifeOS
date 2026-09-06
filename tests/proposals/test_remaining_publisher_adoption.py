from __future__ import annotations

import errno
import os
from pathlib import Path
from types import ModuleType
from typing import Callable

import pytest

import lifeos.copilot.proposals as copilot_proposals
import lifeos.copilot.replanning as replanning
import lifeos.feedback.proposals as feedback_proposals
import lifeos.ownership.reconciliation as ownership_reconciliation
import lifeos.reviews.decisions as review_decisions
from lifeos.ingestion import _proposals_core as ingestion_core
from lifeos.proposals.publication import ProposalPublicationError


PublisherAdapter = Callable[..., object]


def _review_bytes(**_: object) -> bytes:
    return b"{}\n"


def _raise_publish_failure(**_: object) -> None:
    raise ProposalPublicationError("proposal_publish_failed", "injected write failure")


def _feature_adapters() -> tuple[tuple[ModuleType, PublisherAdapter, type[Exception], str], ...]:
    return (
        (
            copilot_proposals,
            copilot_proposals._publish,
            copilot_proposals.CopilotProposalError,
            "could not publish copilot proposal",
        ),
        (
            replanning,
            replanning._publish,
            replanning.ReplanningError,
            "could not publish replanning proposal",
        ),
        (
            feedback_proposals,
            feedback_proposals._publish_feedback_proposal,
            feedback_proposals.FeedbackProposalError,
            "Could not publish feedback proposal",
        ),
        (
            review_decisions,
            review_decisions._publish_review_proposal,
            review_decisions.ReviewProposalError,
            "Could not publish review proposal",
        ),
        (
            ownership_reconciliation,
            ownership_reconciliation._publish_proposal,
            ownership_reconciliation.OwnershipReconciliationError,
            "Could not publish ownership release proposal",
        ),
    )


@pytest.mark.parametrize(("module", "adapter", "error_type", "message"), _feature_adapters())
def test_migrated_feature_adapter_maps_shared_publication_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    adapter: PublisherAdapter,
    error_type: type[Exception],
    message: str,
) -> None:
    monkeypatch.setattr(module, "build_review_snapshot_bytes_from_patches", _review_bytes)
    monkeypatch.setattr(module, "publish_proposal_documents", _raise_publish_failure)

    with pytest.raises(error_type, match=message):
        adapter(
            vault_root=tmp_path,
            proposal_id="proposal-test",
            proposal_markdown=b"proposal",
            patches_json=b"patches",
        )


@pytest.mark.parametrize(
    ("module", "adapter", "error_type"), [(a, b, c) for a, b, c, _ in _feature_adapters()]
)
def test_migrated_feature_adapter_preserves_duplicate_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    adapter: PublisherAdapter,
    error_type: type[Exception],
) -> None:
    vault = tmp_path / module.__name__.replace(".", "-")
    vault.mkdir()
    monkeypatch.setattr(module, "build_review_snapshot_bytes_from_patches", _review_bytes)
    kwargs = {
        "vault_root": vault,
        "proposal_id": "proposal-duplicate",
        "proposal_markdown": b"proposal",
        "patches_json": b"patches",
    }
    adapter(**kwargs)
    with pytest.raises(error_type) as duplicate:
        adapter(**kwargs)
    prefix = next(item[3] for item in _feature_adapters() if item[0] is module)
    old_detail = str(
        FileExistsError(
            errno.EEXIST,
            os.strerror(errno.EEXIST),
            str(vault / "proposals" / "proposal-duplicate"),
        )
    )
    assert str(duplicate.value) == f"{prefix}: {old_detail}"
    assert (vault / "proposals" / "proposal-duplicate" / "review.json").read_bytes() == b"{}\n"


def _ingestion_documents() -> ingestion_core.WikiProposalDocuments:
    return ingestion_core.WikiProposalDocuments(
        proposal_id="proposal-ingestion",
        target_path="wiki/target.md",
        proposal_markdown=b"proposal",
        patches_json=b"patches",
    )


def test_ingestion_core_adapter_maps_shared_publication_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingestion_core, "build_review_snapshot_bytes_from_patches", _review_bytes)
    monkeypatch.setattr(ingestion_core, "publish_proposal_documents", _raise_publish_failure)
    with pytest.raises(
        ingestion_core.ProposalPublicationError, match="Failed to write proposal files"
    ):
        ingestion_core._persist_proposal_documents(
            proposals_root=tmp_path / "proposals", documents=_ingestion_documents()
        )


def test_ingestion_core_adapter_preserves_duplicate_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingestion_core, "build_review_snapshot_bytes_from_patches", _review_bytes)
    documents = _ingestion_documents()
    root = tmp_path / "proposals"
    ingestion_core._persist_proposal_documents(proposals_root=root, documents=documents)
    with pytest.raises(
        ingestion_core.ProposalAlreadyExistsError, match="Proposal directory already exists"
    ):
        ingestion_core._persist_proposal_documents(proposals_root=root, documents=documents)


def test_public_ingestion_runtime_uses_core_publication_adapter() -> None:
    import lifeos.ingestion.proposals as public_ingestion

    assert (
        public_ingestion._persist_proposal_documents is ingestion_core._persist_proposal_documents
    )


def test_ingestion_rejects_noncanonical_proposals_root_without_misplacing_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingestion_core, "build_review_snapshot_bytes_from_patches", _review_bytes)
    requested_root = tmp_path / "drafts"
    with pytest.raises(
        ingestion_core.ProposalPublicationError,
        match="canonical proposals directory",
    ):
        ingestion_core._persist_proposal_documents(
            proposals_root=requested_root, documents=_ingestion_documents()
        )
    assert not requested_root.exists()
    assert not (tmp_path / "proposals" / "proposal-ingestion").exists()
