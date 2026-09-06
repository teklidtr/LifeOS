from __future__ import annotations

import os
from pathlib import Path

import pytest

import lifeos.captures.proposals as capture_proposals
import lifeos.proposals.publication as publication_module
from lifeos._atomic_write import AtomicWriteError
from lifeos.captures.proposals import (
    CaptureProposalPreview,
    CaptureProposalRequest,
    CaptureProposalService,
)
from lifeos.proposals.patches import CreateFile, PatchDocumentV2
from lifeos.proposals.publication import (
    ProposalDocuments,
    ProposalPublicationError,
    publish_proposal_documents,
)

PROPOSAL_ID = "proposal-20260906T070000Z-deadbeef"
DOCUMENTS = ProposalDocuments(b"proposal-bytes", b"patch-bytes", b"review-bytes")


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


def test_publisher_writes_exact_documents_and_rejects_duplicate_id(tmp_path: Path) -> None:
    vault = _vault(tmp_path)

    publish_proposal_documents(
        vault_root=vault,
        proposal_id=PROPOSAL_ID,
        documents=DOCUMENTS,
    )

    proposal_dir = vault / "proposals" / PROPOSAL_ID
    assert (proposal_dir / "proposal.md").read_bytes() == DOCUMENTS.proposal_markdown
    assert (proposal_dir / "patches.json").read_bytes() == DOCUMENTS.patches_json
    assert (proposal_dir / "review.json").read_bytes() == DOCUMENTS.review_json

    with pytest.raises(ProposalPublicationError) as duplicate:
        publish_proposal_documents(
            vault_root=vault,
            proposal_id=PROPOSAL_ID,
            documents=DOCUMENTS,
        )
    assert duplicate.value.code == "proposal_exists"
    assert (proposal_dir / "proposal.md").read_bytes() == DOCUMENTS.proposal_markdown


@pytest.mark.parametrize(
    "proposal_id",
    ("", ".", "..", "../escape", "nested/id", "nested\\id", "bad\x00id"),
)
def test_publisher_rejects_unsafe_proposal_ids(tmp_path: Path, proposal_id: str) -> None:
    vault = _vault(tmp_path)

    with pytest.raises(ProposalPublicationError) as unsafe:
        publish_proposal_documents(
            vault_root=vault,
            proposal_id=proposal_id,
            documents=DOCUMENTS,
        )

    assert unsafe.value.code == "unsafe_proposal_id"
    assert not (vault / "proposals").exists()


def test_publisher_rejects_symlinked_proposals_root_without_touching_target(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    try:
        (vault / "proposals").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(ProposalPublicationError) as unsafe:
        publish_proposal_documents(
            vault_root=vault,
            proposal_id=PROPOSAL_ID,
            documents=DOCUMENTS,
        )

    assert unsafe.value.code == "unsafe_proposals_root"
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (outside / PROPOSAL_ID).exists()


def test_partial_write_cleans_only_owned_proposal_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path)
    original = publication_module.atomic_write_file_secure

    def fail_second_write(dir_fd: int, filename: str, content: bytes):
        if filename == "patches.json":
            raise AtomicWriteError("injected patch write failure", write_occurred=False)
        return original(dir_fd, filename, content)

    monkeypatch.setattr(publication_module, "atomic_write_file_secure", fail_second_write)

    with pytest.raises(ProposalPublicationError) as failed:
        publish_proposal_documents(
            vault_root=vault,
            proposal_id=PROPOSAL_ID,
            documents=DOCUMENTS,
        )

    assert failed.value.code == "proposal_publish_failed"
    assert not (vault / "proposals" / PROPOSAL_ID).exists()


def test_replaced_proposal_directory_is_never_removed_by_failed_attempt_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path)
    original = publication_module.atomic_write_file_secure
    proposals_root = vault / "proposals"
    detached = proposals_root / f"{PROPOSAL_ID}-detached"
    replacement = proposals_root / PROPOSAL_ID

    def replace_directory_after_first_write(dir_fd: int, filename: str, content: bytes):
        result = original(dir_fd, filename, content)
        if filename == "proposal.md":
            os.rename(replacement, detached)
            replacement.mkdir()
            (replacement / "keep.txt").write_text("replacement", encoding="utf-8")
        return result

    monkeypatch.setattr(
        publication_module,
        "atomic_write_file_secure",
        replace_directory_after_first_write,
    )

    with pytest.raises(ProposalPublicationError) as replaced:
        publish_proposal_documents(
            vault_root=vault,
            proposal_id=PROPOSAL_ID,
            documents=DOCUMENTS,
        )

    assert replaced.value.code == "proposal_publish_failed"
    assert (replacement / "keep.txt").read_text(encoding="utf-8") == "replacement"
    assert not (detached / "proposal.md").exists()


def test_replaced_proposal_symlink_and_target_are_not_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("outside", encoding="utf-8")
    original = publication_module.atomic_write_file_secure
    proposals_root = vault / "proposals"
    detached = proposals_root / f"{PROPOSAL_ID}-detached"
    publication_path = proposals_root / PROPOSAL_ID

    def replace_with_symlink_after_first_write(dir_fd: int, filename: str, content: bytes):
        result = original(dir_fd, filename, content)
        if filename == "proposal.md":
            os.rename(publication_path, detached)
            try:
                publication_path.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                pytest.skip(f"symlink creation is unavailable: {exc}")
        return result

    monkeypatch.setattr(
        publication_module,
        "atomic_write_file_secure",
        replace_with_symlink_after_first_write,
    )

    with pytest.raises(ProposalPublicationError):
        publish_proposal_documents(
            vault_root=vault,
            proposal_id=PROPOSAL_ID,
            documents=DOCUMENTS,
        )

    assert publication_path.is_symlink()
    assert marker.read_text(encoding="utf-8") == "outside"
    assert not (detached / "proposal.md").exists()


def test_capture_review_generation_failure_happens_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path)
    service = CaptureProposalService(
        vault_root=vault,
        runtime_dir=vault / ".lifeos",
        actor_id="tester",
    )
    preview = CaptureProposalPreview(
        proposal_id=PROPOSAL_ID,
        target_path="notes/new.md",
        operation="create_file",
        base_hash=None,
        source_capture_id="capture-1",
        source_capture_hash="sha256:" + "a" * 64,
        attachment_ids=(),
        included_actions=(),
        excluded_actions=(),
    )
    patch = PatchDocumentV2(
        2,
        PROPOSAL_ID,
        (CreateFile("op-create", "notes/new.md", "absent", "content\n"),),
    )
    request = CaptureProposalRequest(
        capture_path="captures/unused.md",
        action="create-note",
        target_path="notes/new.md",
        content="content",
        create_target=True,
    )
    published = False

    def preview_stub(_request: CaptureProposalRequest, *, now=None):
        return preview, patch, b"proposal"

    def fail_review(**_kwargs):
        raise RuntimeError("injected review generation failure")

    def publication_spy(**_kwargs):
        nonlocal published
        published = True

    monkeypatch.setattr(service, "preview", preview_stub)
    monkeypatch.setattr(capture_proposals, "build_review_snapshot_bytes_from_patches", fail_review)
    monkeypatch.setattr(capture_proposals, "publish_proposal_documents", publication_spy)

    with pytest.raises(RuntimeError, match="review generation"):
        service.publish(request)

    assert not published
    assert not (vault / "proposals").exists()
