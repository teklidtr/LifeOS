from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.facade.authorization import (
    AuthorizedPrincipal,
    ConsequentialAuthorizationRequest,
)
from lifeos.facade.consequential_tools import (
    AcceptProposalRequest,
    ApplyProposalRequest,
    accept_proposal_tool,
    apply_proposal_tool,
)
from lifeos.facade.errors import ToolConflictError, ToolExecutionError
from lifeos.facade.registry_tools import refresh_registry
from lifeos.proposals.lifecycle import compute_review_digest, serialize_proposal_markdown
from lifeos.proposals.loader import load_proposal_directory
from lifeos.proposals.patches import (
    PatchDocumentV2,
    ReplaceGeneratedFileV2,
    ReplaceManagedBlock,
    serialize_patch_json_bytes,
)
from lifeos.proposals.schema import ProposalStatus, validate_metadata
from lifeos.registry import Registry
from lifeos.registry.proposals import list_proposals

PROPOSAL_ID = "prop-20260828T120000Z-a1646abc"
ZERO_DIGEST = "sha256:" + ("0" * 64)


class AllowingAuthorizer:
    def __init__(self) -> None:
        self.requests: list[ConsequentialAuthorizationRequest] = []

    def authorize(
        self, request: ConsequentialAuthorizationRequest, /
    ) -> AuthorizedPrincipal:
        self.requests.append(request)
        return AuthorizedPrincipal("lifeos-1646-test")


def _clock() -> datetime:
    return datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _metadata(*, review_digest: str, status: str = "approved"):
    values = {
        "id": PROPOSAL_ID,
        "schema_version": 1,
        "patch_schema_version": 2,
        "lifecycle_schema_version": 1,
        "title": "Registry disposability invariant",
        "description": "Regression fixture for canonical proposal authority.",
        "status": status,
        "risk": "high",
        "created_at": "2026-08-28T09:00:00Z",
        "created_by": "test",
        "submitted_at": "2026-08-28T09:10:00Z",
        "submitted_by": "test",
        "review_digest": review_digest,
        "approved_at": "2026-08-28T09:20:00Z",
        "approved_by": "test",
        "rejected_at": None,
        "rejected_by": None,
        "rejection_reason": None,
        "applied_at": None,
        "applied_by": None,
        "related_goals": [],
        "related_sources": [],
        "extensions": {},
    }
    return validate_metadata(values)


def _write_approved_proposal(vault_root: Path, patch_document: PatchDocumentV2) -> Path:
    proposals_root = vault_root / "proposals"
    proposal_dir = proposals_root / PROPOSAL_ID
    proposal_dir.mkdir(parents=True, exist_ok=True)
    body = "# Registry disposability regression\n"

    metadata = _metadata(review_digest=ZERO_DIGEST)
    (proposal_dir / "proposal.md").write_bytes(
        serialize_proposal_markdown(metadata, body)
    )
    (proposal_dir / "patches.json").write_bytes(
        serialize_patch_json_bytes(patch_document)
    )

    loaded = load_proposal_directory(proposal_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None
    assert not loaded.findings
    review_digest = compute_review_digest(
        loaded.proposal.metadata,
        loaded.proposal.body,
        loaded.proposal.patch_document,
        loaded.proposal.review_snapshot,
    )

    metadata = _metadata(review_digest=review_digest)
    (proposal_dir / "proposal.md").write_bytes(
        serialize_proposal_markdown(metadata, body)
    )
    return proposal_dir


def _write_ownership(
    vault_root: Path, owned_files: dict[str, dict[str, str]] | None = None
) -> Path:
    manifest = vault_root / "system" / "generated-ownership.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {"schema_version": 1, "owned_files": owned_files or {}},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest


def _initialize_git_and_registry(vault_root: Path) -> tuple[Path, Registry]:
    subprocess.run(
        ["git", "init"], cwd=vault_root, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "add", "-A"], cwd=vault_root, check=True, capture_output=True
    )
    registry_path = vault_root / ".lifeos" / "registry.db"
    registry = Registry(registry_path)
    refresh_registry(vault_root=vault_root, registry=registry)
    return registry_path, registry


def _delete_registry_files(registry_path: Path) -> None:
    for candidate in (
        registry_path,
        Path(f"{registry_path}-wal"),
        Path(f"{registry_path}-shm"),
    ):
        candidate.unlink(missing_ok=True)


def _assert_refused_without_writes(
    *,
    vault_root: Path,
    target_path: Path,
    expected_target: bytes,
    ownership_path: Path,
    expected_ownership: bytes,
    proposal_path: Path,
    facade: str = "apply",
    error_fragment: str = "Preflight failed",
) -> None:
    authorizer = AllowingAuthorizer()
    with pytest.raises(ToolExecutionError, match=error_fragment):
        if facade == "accept":
            accept_proposal_tool(
                vault_root=vault_root,
                request=AcceptProposalRequest(PROPOSAL_ID),
                authorizer=authorizer,
                clock_fn=_clock,
            )
        else:
            apply_proposal_tool(
                vault_root=vault_root,
                request=ApplyProposalRequest(PROPOSAL_ID),
                authorizer=authorizer,
                clock_fn=_clock,
            )

    assert len(authorizer.requests) == 1
    assert target_path.read_bytes() == expected_target
    assert ownership_path.read_bytes() == expected_ownership
    proposal_text = proposal_path.read_text(encoding="utf-8")
    assert "status: approved" in proposal_text
    assert "status: applied" not in proposal_text


def test_stale_human_target_stays_refused_through_apply_and_accept_after_registry_loss(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    target = vault_root / "wiki" / "human.md"
    target.parent.mkdir(parents=True)
    original = (
        b"# Human note\n"
        b"<!-- lifeos:managed:start summary -->\n"
        b"original\n"
        b"<!-- lifeos:managed:end summary -->\n"
    )
    target.write_bytes(original)
    ownership_path = _write_ownership(vault_root)

    operation = ReplaceManagedBlock(
        id="op-human",
        target_path="wiki/human.md",
        base_hash=_sha256(original),
        block_name="summary",
        new_content="proposed\n",
    )
    proposal_dir = _write_approved_proposal(
        vault_root,
        PatchDocumentV2(2, PROPOSAL_ID, (operation,)),
    )
    proposal_path = proposal_dir / "proposal.md"
    registry_path, _registry = _initialize_git_and_registry(vault_root)

    concurrent = original.replace(b"original\n", b"concurrent user edit\n")
    target.write_bytes(concurrent)
    ownership_bytes = ownership_path.read_bytes()

    _assert_refused_without_writes(
        vault_root=vault_root,
        target_path=target,
        expected_target=concurrent,
        ownership_path=ownership_path,
        expected_ownership=ownership_bytes,
        proposal_path=proposal_path,
    )

    _delete_registry_files(registry_path)
    assert not registry_path.exists()
    _assert_refused_without_writes(
        vault_root=vault_root,
        target_path=target,
        expected_target=concurrent,
        ownership_path=ownership_path,
        expected_ownership=ownership_bytes,
        proposal_path=proposal_path,
        facade="accept",
    )

    rebuilt = Registry(registry_path)
    refresh_registry(vault_root=vault_root, registry=rebuilt)
    assert registry_path.exists()
    _assert_refused_without_writes(
        vault_root=vault_root,
        target_path=target,
        expected_target=concurrent,
        ownership_path=ownership_path,
        expected_ownership=ownership_bytes,
        proposal_path=proposal_path,
        facade="accept",
    )


def test_generated_ownership_conflict_stays_refused_after_registry_loss_and_rebuild(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    target = vault_root / "wiki" / "generated.md"
    target.parent.mkdir(parents=True)
    original = b"# Generated\noriginal\n"
    target.write_bytes(original)
    ownership_path = _write_ownership(
        vault_root,
        {
            "wiki/generated.md": {
                "generator_id": "gen-1",
                "generator_version": "v1",
                "content_hash": hashlib.sha256(original).hexdigest(),
                "created_at": "2026-08-28T09:00:00Z",
                "updated_at": "2026-08-28T09:00:00Z",
            }
        },
    )

    operation = ReplaceGeneratedFileV2(
        id="op-generated",
        target_path="wiki/generated.md",
        base_hash=_sha256(original),
        expected_generator_id="gen-1",
        generator_version="v1",
        new_content="# Generated\nreplacement\n",
    )
    proposal_dir = _write_approved_proposal(
        vault_root,
        PatchDocumentV2(2, PROPOSAL_ID, (operation,)),
    )
    proposal_path = proposal_dir / "proposal.md"
    registry_path, _registry = _initialize_git_and_registry(vault_root)

    ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
    ownership["owned_files"]["wiki/generated.md"]["generator_id"] = "gen-2"
    ownership_path.write_text(
        json.dumps(ownership, sort_keys=True),
        encoding="utf-8",
    )
    ownership_bytes = ownership_path.read_bytes()

    _assert_refused_without_writes(
        vault_root=vault_root,
        target_path=target,
        expected_target=original,
        ownership_path=ownership_path,
        expected_ownership=ownership_bytes,
        proposal_path=proposal_path,
        error_fragment="Generator identity mismatch",
    )

    _delete_registry_files(registry_path)
    _assert_refused_without_writes(
        vault_root=vault_root,
        target_path=target,
        expected_target=original,
        ownership_path=ownership_path,
        expected_ownership=ownership_bytes,
        proposal_path=proposal_path,
        error_fragment="Generator identity mismatch",
    )

    rebuilt = Registry(registry_path)
    refresh_registry(vault_root=vault_root, registry=rebuilt)
    _assert_refused_without_writes(
        vault_root=vault_root,
        target_path=target,
        expected_target=original,
        ownership_path=ownership_path,
        expected_ownership=ownership_bytes,
        proposal_path=proposal_path,
        error_fragment="Generator identity mismatch",
    )


def test_applied_lifecycle_remains_canonical_after_registry_deletion_and_rebuild(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    ownership_path = _write_ownership(vault_root)
    proposal_dir = _write_approved_proposal(
        vault_root,
        PatchDocumentV2(2, PROPOSAL_ID, ()),
    )
    proposal_path = proposal_dir / "proposal.md"
    registry_path, registry = _initialize_git_and_registry(vault_root)

    result = apply_proposal_tool(
        vault_root=vault_root,
        request=ApplyProposalRequest(PROPOSAL_ID),
        authorizer=AllowingAuthorizer(),
        clock_fn=_clock,
    )
    assert result.status == "applied"
    assert "status: applied" in proposal_path.read_text(encoding="utf-8")
    ownership_bytes = ownership_path.read_bytes()

    refresh_registry(vault_root=vault_root, registry=registry)
    with registry.connect() as connection:
        summaries = list_proposals(connection)
    assert len(summaries) == 1
    assert summaries[0].status is ProposalStatus.APPLIED

    _delete_registry_files(registry_path)
    assert not registry_path.exists()
    with pytest.raises(ToolConflictError, match="Cannot apply from applied"):
        apply_proposal_tool(
            vault_root=vault_root,
            request=ApplyProposalRequest(PROPOSAL_ID),
            authorizer=AllowingAuthorizer(),
            clock_fn=_clock,
        )
    assert "status: applied" in proposal_path.read_text(encoding="utf-8")
    assert ownership_path.read_bytes() == ownership_bytes

    rebuilt = Registry(registry_path)
    refresh_registry(vault_root=vault_root, registry=rebuilt)
    with rebuilt.connect() as connection:
        summaries = list_proposals(connection)
    assert len(summaries) == 1
    assert summaries[0].status is ProposalStatus.APPLIED

    with pytest.raises(ToolConflictError, match="Cannot apply from applied"):
        apply_proposal_tool(
            vault_root=vault_root,
            request=ApplyProposalRequest(PROPOSAL_ID),
            authorizer=AllowingAuthorizer(),
            clock_fn=_clock,
        )
    assert "status: applied" in proposal_path.read_text(encoding="utf-8")
    assert ownership_path.read_bytes() == ownership_bytes


def test_review_digest_tampering_stays_refused_after_registry_deletion_and_rebuild(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    target = vault_root / "wiki" / "digest-target.md"
    target.parent.mkdir(parents=True)
    original = (
        b"# Digest target\n"
        b"<!-- lifeos:managed:start summary -->\n"
        b"original\n"
        b"<!-- lifeos:managed:end summary -->\n"
    )
    target.write_bytes(original)
    ownership_path = _write_ownership(vault_root)

    initial_operation = ReplaceManagedBlock(
        id="op-digest",
        target_path="wiki/digest-target.md",
        base_hash=_sha256(original),
        block_name="summary",
        new_content="reviewed\n",
    )
    proposal_dir = _write_approved_proposal(
        vault_root,
        PatchDocumentV2(2, PROPOSAL_ID, (initial_operation,)),
    )
    proposal_path = proposal_dir / "proposal.md"
    patches_path = proposal_dir / "patches.json"
    registry_path, _registry = _initialize_git_and_registry(vault_root)

    tampered_operation = ReplaceManagedBlock(
        id="op-digest",
        target_path="wiki/digest-target.md",
        base_hash=_sha256(original),
        block_name="summary",
        new_content="tampered after review\n",
    )
    patches_path.write_bytes(
        serialize_patch_json_bytes(
            PatchDocumentV2(2, PROPOSAL_ID, (tampered_operation,))
        )
    )

    ownership_bytes = ownership_path.read_bytes()
    proposal_bytes = proposal_path.read_bytes()

    def assert_digest_refused() -> None:
        authorizer = AllowingAuthorizer()
        with pytest.raises(
            ToolConflictError,
            match="Current proposal content does not match stored review digest",
        ):
            apply_proposal_tool(
                vault_root=vault_root,
                request=ApplyProposalRequest(PROPOSAL_ID),
                authorizer=authorizer,
                clock_fn=_clock,
            )
        assert authorizer.requests == []
        assert target.read_bytes() == original
        assert ownership_path.read_bytes() == ownership_bytes
        assert proposal_path.read_bytes() == proposal_bytes

    assert_digest_refused()

    _delete_registry_files(registry_path)
    assert_digest_refused()

    rebuilt = Registry(registry_path)
    refresh_registry(vault_root=vault_root, registry=rebuilt)
    assert_digest_refused()
