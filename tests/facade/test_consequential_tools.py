import pytest
from pathlib import Path
import json
from lifeos.proposals.lifecycle import compute_review_digest
from lifeos.proposals.loader import load_proposal_directory
from datetime import datetime, timezone

from lifeos.facade.authorization import (
    AuthorizedPrincipal,
    ConsequentialAuthorizationRequest,
    ConsequentialAction,
    AuthorizationDeniedError,
    AuthorizationUnavailableError,
)
from lifeos.facade.consequential_tools import (
    submit_proposal_tool,
    approve_proposal_tool,
    apply_proposal_tool,
    SubmitProposalRequest,
    ApproveProposalRequest,
    ApplyProposalRequest,
)
from lifeos.facade.errors import (
    ToolAuthorizationError,
    ToolConflictError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolUnavailableError,
)


class MockAuthorizer:
    def __init__(self, actor_id: str = "test_actor"):
        self.actor_id = actor_id
        self.requests: list[ConsequentialAuthorizationRequest] = []
        self.error: Exception | None = None

    def authorize(self, request: ConsequentialAuthorizationRequest, /) -> AuthorizedPrincipal:
        self.requests.append(request)
        if self.error:
            raise self.error
        return AuthorizedPrincipal(self.actor_id)


class MockClock:
    def __init__(self):
        self.calls = 0
        self.time = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self.calls += 1
        return self.time


def _create_draft(
    proposals_root: Path, proposal_id: str = "prop-20260714T120000Z-1234abcd"
) -> Path:
    prop_dir = proposals_root / proposal_id
    prop_dir.mkdir(parents=True, exist_ok=True)
    (prop_dir / "proposal.md").write_text(f"""---
id: {proposal_id}
schema_version: 1
patch_schema_version: 1
lifecycle_schema_version: 1
title: Test Proposal
description: desc
risk: low
status: draft
created_at: "2020-01-01T12:00:00Z"
created_by: user1
---
# Proposal""")
    (prop_dir / "patches.json").write_bytes(
        (
            json.dumps(
                {"operations": [], "proposal_id": proposal_id, "schema_version": 1},
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    return prop_dir


def _create_pending(
    proposals_root: Path, digest: str, proposal_id: str = "prop-20260714T120000Z-1234abcd"
) -> Path:
    prop_dir = proposals_root / proposal_id
    prop_dir.mkdir(parents=True, exist_ok=True)
    (prop_dir / "proposal.md").write_text(f"""---
id: {proposal_id}
schema_version: 1
patch_schema_version: 1
lifecycle_schema_version: 1
title: Test Proposal
description: desc
risk: low
status: pending
created_at: "2020-01-01T12:00:00Z"
created_by: user1
submitted_at: "2020-01-01T12:00:00Z"
submitted_by: user1
review_digest: {digest}
---
# Proposal""")
    (prop_dir / "patches.json").write_bytes(
        (
            json.dumps(
                {"operations": [], "proposal_id": proposal_id, "schema_version": 1},
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    return prop_dir


def _create_approved(
    proposals_root: Path, digest: str, proposal_id: str = "prop-20260714T120000Z-1234abcd"
) -> Path:
    prop_dir = proposals_root / proposal_id
    prop_dir.mkdir(parents=True, exist_ok=True)
    (prop_dir / "proposal.md").write_text(f"""---
id: {proposal_id}
schema_version: 1
patch_schema_version: 1
lifecycle_schema_version: 1
title: Test Proposal
description: desc
risk: low
status: approved
created_at: "2020-01-01T12:00:00Z"
created_by: user1
submitted_at: "2020-01-01T12:00:00Z"
submitted_by: user1
approved_at: "2020-01-01T12:00:00Z"
approved_by: user1
review_digest: {digest}
---
# Proposal""")
    (prop_dir / "patches.json").write_bytes(
        (
            json.dumps(
                {"operations": [], "proposal_id": proposal_id, "schema_version": 1},
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    return prop_dir


def test_submit_draft_proposal(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_draft(proposals, "prop-20260714T120000Z-1234abcd")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    clock = MockClock()

    res = submit_proposal_tool(
        vault_root=vault,
        request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
        authorizer=authorizer,
        clock_fn=clock,
    )

    assert res.proposal_id == "prop-20260714T120000Z-1234abcd"
    assert res.status == "pending"
    assert res.review_digest

    assert len(authorizer.requests) == 1
    req = authorizer.requests[0]
    assert req.action == ConsequentialAction.SUBMIT
    assert req.proposal_id == "prop-20260714T120000Z-1234abcd"
    assert req.review_digest is None

    assert clock.calls == 1

    content = (proposals / "prop-20260714T120000Z-1234abcd" / "proposal.md").read_text()
    assert "status: pending" in content
    assert "submitted_by: userX" in content


def test_submit_invalid_transition_maps_to_conflict(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_pending(proposals, digest="fake-digest", proposal_id="prop-20260714T120000Z-1234abcd")

    with pytest.raises(ToolConflictError, match="Cannot submit from pending"):
        submit_proposal_tool(
            vault_root=vault,
            request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
            authorizer=MockAuthorizer(),
        )


def test_submit_denial_leaves_draft_unchanged(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_draft(proposals, "prop-20260714T120000Z-1234abcd")
    original = (proposals / "prop-20260714T120000Z-1234abcd" / "proposal.md").read_text()

    authorizer = MockAuthorizer()
    authorizer.error = AuthorizationDeniedError()

    with pytest.raises(ToolAuthorizationError):
        submit_proposal_tool(
            vault_root=vault,
            request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
            authorizer=authorizer,
        )

    assert (proposals / "prop-20260714T120000Z-1234abcd" / "proposal.md").read_text() == original


def test_submit_authorization_has_no_digest(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_draft(proposals, "prop-20260714T120000Z-1234abcd")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    submit_proposal_tool(
        vault_root=vault,
        request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
        authorizer=authorizer,
    )

    assert len(authorizer.requests) == 1
    assert authorizer.requests[0].review_digest is None


def test_submit_returns_internally_generated_digest(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_draft(proposals, "prop-20260714T120000Z-1234abcd")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    res = submit_proposal_tool(
        vault_root=vault,
        request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
        authorizer=authorizer,
    )

    assert res.review_digest is not None
    assert res.review_digest.startswith("sha256:")


def test_submit_uses_authorized_actor(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_draft(proposals, "prop-20260714T120000Z-1234abcd")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    submit_proposal_tool(
        vault_root=vault,
        request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
        authorizer=authorizer,
    )

    content = (proposals / "prop-20260714T120000Z-1234abcd" / "proposal.md").read_text()
    assert "submitted_by: userX" in content


def test_submit_calls_clock_once(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_draft(proposals, "prop-20260714T120000Z-1234abcd")

    clock = MockClock()
    submit_proposal_tool(
        vault_root=vault,
        request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
        authorizer=MockAuthorizer("userX"),
        clock_fn=clock,
    )

    assert clock.calls == 1


def test_authorization_denied_maps_to_tool_authorization_error(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_draft(proposals, "prop-20260714T120000Z-1234abcd")
    authorizer = MockAuthorizer()
    authorizer.error = AuthorizationDeniedError()
    with pytest.raises(ToolAuthorizationError):
        submit_proposal_tool(
            vault_root=vault,
            request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
            authorizer=authorizer,
        )


def test_authorization_unavailable_maps_to_tool_unavailable_error(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_draft(proposals, "prop-20260714T120000Z-1234abcd")
    authorizer = MockAuthorizer()
    authorizer.error = AuthorizationUnavailableError()
    with pytest.raises(ToolUnavailableError):
        submit_proposal_tool(
            vault_root=vault,
            request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
            authorizer=authorizer,
        )


def test_missing_proposal_maps_to_not_found(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    with pytest.raises(ToolNotFoundError):
        submit_proposal_tool(
            vault_root=vault,
            request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
            authorizer=MockAuthorizer(),
        )


def test_malformed_proposal_maps_to_execution_error(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    prop = proposals / "prop-20260714T120000Z-1234abcd"
    prop.mkdir(parents=True)
    # create malformed md (no schema)
    (prop / "proposal.md").write_text("invalid")
    with pytest.raises(ToolExecutionError):
        submit_proposal_tool(
            vault_root=vault,
            request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
            authorizer=MockAuthorizer(),
        )


def test_unexpected_authorizer_error_propagates(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_draft(proposals, "prop-20260714T120000Z-1234abcd")
    authorizer = MockAuthorizer()
    authorizer.error = ValueError("Authorizer blew up")
    with pytest.raises(ValueError, match="Authorizer blew up"):
        submit_proposal_tool(
            vault_root=vault,
            request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
            authorizer=authorizer,
        )


def test_approve_verifies_current_digest_before_authorization(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_pending(proposals, digest="fake-digest", proposal_id="prop-20260714T120000Z-1234abcd")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    with pytest.raises(
        ToolConflictError, match="Current proposal content does not match stored review digest"
    ):
        approve_proposal_tool(
            vault_root=vault,
            request=ApproveProposalRequest(
                proposal_id="prop-20260714T120000Z-1234abcd",
            ),
            authorizer=authorizer,
            clock_fn=MockClock(),
        )
    assert len(authorizer.requests) == 0


def test_approve_authorization_binds_current_digest(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"

    _create_pending(
        proposals, digest="to-be-overwritten", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    res = load_proposal_directory(
        proposals / "prop-20260714T120000Z-1234abcd", proposals_root=proposals
    )
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )

    _create_pending(proposals, digest=actual_digest, proposal_id="prop-20260714T120000Z-1234abcd")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    approve_proposal_tool(
        vault_root=vault,
        request=ApproveProposalRequest(
            proposal_id="prop-20260714T120000Z-1234abcd",
        ),
        authorizer=authorizer,
        clock_fn=MockClock(),
    )

    assert len(authorizer.requests) == 1
    assert authorizer.requests[0].review_digest == actual_digest
    assert authorizer.requests[0].action == ConsequentialAction.APPROVE


def test_approve_digest_mismatch_does_not_call_authorizer(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_pending(
        proposals,
        digest="sha256:" + "0" * 64,
        proposal_id="prop-20260714T120000Z-1234abcd",
    )
    authorizer = MockAuthorizer()

    with pytest.raises(ToolConflictError, match="does not match stored review digest"):
        approve_proposal_tool(
            vault_root=vault,
            request=ApproveProposalRequest("prop-20260714T120000Z-1234abcd"),
            authorizer=authorizer,
        )

    assert authorizer.requests == []


def test_approve_uses_authorized_actor(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"

    _create_pending(
        proposals, digest="to-be-overwritten", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    res = load_proposal_directory(
        proposals / "prop-20260714T120000Z-1234abcd", proposals_root=proposals
    )
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )
    _create_pending(proposals, digest=actual_digest, proposal_id="prop-20260714T120000Z-1234abcd")

    authorizer = MockAuthorizer("userY")
    approve_proposal_tool(
        vault_root=vault,
        request=ApproveProposalRequest(
            proposal_id="prop-20260714T120000Z-1234abcd",
        ),
        authorizer=authorizer,
        clock_fn=MockClock(),
    )

    content = (proposals / "prop-20260714T120000Z-1234abcd" / "proposal.md").read_text()
    assert "approved_by: userY" in content


def test_approve_calls_clock_once(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"

    _create_pending(
        proposals, digest="to-be-overwritten", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    res = load_proposal_directory(
        proposals / "prop-20260714T120000Z-1234abcd", proposals_root=proposals
    )
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )
    _create_pending(proposals, digest=actual_digest, proposal_id="prop-20260714T120000Z-1234abcd")

    clock = MockClock()
    approve_proposal_tool(
        vault_root=vault,
        request=ApproveProposalRequest(
            proposal_id="prop-20260714T120000Z-1234abcd",
        ),
        authorizer=MockAuthorizer("userY"),
        clock_fn=clock,
    )

    assert clock.calls == 1


def test_approve_denial_leaves_pending_unchanged(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"

    _create_pending(
        proposals, digest="to-be-overwritten", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    res = load_proposal_directory(
        proposals / "prop-20260714T120000Z-1234abcd", proposals_root=proposals
    )
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )
    _create_pending(proposals, digest=actual_digest, proposal_id="prop-20260714T120000Z-1234abcd")

    original = (proposals / "prop-20260714T120000Z-1234abcd" / "proposal.md").read_text()

    authorizer = MockAuthorizer("userY")
    authorizer.error = AuthorizationDeniedError()

    with pytest.raises(ToolAuthorizationError):
        approve_proposal_tool(
            vault_root=vault,
            request=ApproveProposalRequest(
                proposal_id="prop-20260714T120000Z-1234abcd",
            ),
            authorizer=authorizer,
            clock_fn=MockClock(),
        )

    assert (proposals / "prop-20260714T120000Z-1234abcd" / "proposal.md").read_text() == original


class MutatingAuthorizer:
    def __init__(self, proposals: Path):
        self.proposals = proposals

    def authorize(self, request: ConsequentialAuthorizationRequest, /) -> AuthorizedPrincipal:
        (self.proposals / request.proposal_id / "proposal.md").write_text("modified")
        return AuthorizedPrincipal("userZ")


def test_approve_changed_content_after_authorization_is_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"

    _create_pending(
        proposals, digest="to-be-overwritten", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    res = load_proposal_directory(
        proposals / "prop-20260714T120000Z-1234abcd", proposals_root=proposals
    )
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )
    _create_pending(proposals, digest=actual_digest, proposal_id="prop-20260714T120000Z-1234abcd")

    authorizer = MutatingAuthorizer(proposals)

    with pytest.raises(ToolConflictError, match="Conflict during transition"):
        approve_proposal_tool(
            vault_root=vault,
            request=ApproveProposalRequest(
                proposal_id="prop-20260714T120000Z-1234abcd",
            ),
            authorizer=authorizer,
            clock_fn=MockClock(),
        )


# --- Apply Tool Tests ---


def _create_approved(
    proposals_root: Path, digest: str, proposal_id: str = "prop-20260714T120000Z-1234abcd"
) -> Path:
    prop_dir = proposals_root / proposal_id
    prop_dir.mkdir(parents=True, exist_ok=True)
    (prop_dir / "proposal.md").write_text(f"""---
id: {proposal_id}
schema_version: 1
patch_schema_version: 1
lifecycle_schema_version: 1
title: Test Proposal
description: desc
risk: low
status: approved
created_at: "2020-01-01T12:00:00Z"
created_by: user1
submitted_at: "2020-01-01T12:00:00Z"
submitted_by: user1
approved_at: "2020-01-01T12:00:00Z"
approved_by: user1
review_digest: {digest}
---
# Proposal""")
    (prop_dir / "patches.json").write_bytes(
        (
            json.dumps(
                {"operations": [], "proposal_id": proposal_id, "schema_version": 1},
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    return prop_dir


def test_apply_requires_separate_authorization(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_approved(
        proposals, digest="to-be-overwritten", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    res = load_proposal_directory(
        proposals / "prop-20260714T120000Z-1234abcd", proposals_root=proposals
    )
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )
    _create_approved(proposals, digest=actual_digest, proposal_id="prop-20260714T120000Z-1234abcd")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    apply_proposal_tool(
        vault_root=vault,
        request=ApplyProposalRequest(proposal_id="prop-20260714T120000Z-1234abcd"),
        authorizer=authorizer,
        clock_fn=MockClock(),
    )

    assert len(authorizer.requests) == 1
    assert authorizer.requests[0].action == ConsequentialAction.APPLY


def test_apply_verifies_current_digest_before_authorization(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_approved(
        proposals, digest="to-be-overwritten", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    res = load_proposal_directory(
        proposals / "prop-20260714T120000Z-1234abcd", proposals_root=proposals
    )
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )
    _create_approved(proposals, digest=actual_digest, proposal_id="prop-20260714T120000Z-1234abcd")

    # Mutate
    prop_path = proposals / "prop-20260714T120000Z-1234abcd" / "proposal.md"
    prop_path.write_text(prop_path.read_text() + "\n# mutated")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    with pytest.raises(
        ToolConflictError, match="Current proposal content does not match stored review digest"
    ):
        apply_proposal_tool(
            vault_root=vault,
            request=ApplyProposalRequest(proposal_id="prop-20260714T120000Z-1234abcd"),
            authorizer=authorizer,
            clock_fn=MockClock(),
        )
    assert len(authorizer.requests) == 0


def test_apply_authorization_binds_current_digest(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_approved(
        proposals, digest="to-be-overwritten", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    res = load_proposal_directory(
        proposals / "prop-20260714T120000Z-1234abcd", proposals_root=proposals
    )
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )
    _create_approved(proposals, digest=actual_digest, proposal_id="prop-20260714T120000Z-1234abcd")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    apply_proposal_tool(
        vault_root=vault,
        request=ApplyProposalRequest(proposal_id="prop-20260714T120000Z-1234abcd"),
        authorizer=authorizer,
        clock_fn=MockClock(),
    )

    assert len(authorizer.requests) == 1
    assert authorizer.requests[0].review_digest == actual_digest


def test_apply_digest_mismatch_does_not_call_authorizer(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_approved(
        proposals, digest="mismatched-digest", proposal_id="prop-20260714T120000Z-1234abcd"
    )

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    with pytest.raises(ToolConflictError):
        apply_proposal_tool(
            vault_root=vault,
            request=ApplyProposalRequest(proposal_id="prop-20260714T120000Z-1234abcd"),
            authorizer=authorizer,
            clock_fn=MockClock(),
        )
    assert len(authorizer.requests) == 0


def test_apply_uses_authorized_actor(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_approved(
        proposals, digest="to-be-overwritten", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    res = load_proposal_directory(
        proposals / "prop-20260714T120000Z-1234abcd", proposals_root=proposals
    )
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )
    _create_approved(proposals, digest=actual_digest, proposal_id="prop-20260714T120000Z-1234abcd")

    authorizer = MockAuthorizer("special_user")
    apply_proposal_tool(
        vault_root=vault,
        request=ApplyProposalRequest(proposal_id="prop-20260714T120000Z-1234abcd"),
        authorizer=authorizer,
        clock_fn=MockClock(),
    )

    # Read applied_by
    content = (proposals / "prop-20260714T120000Z-1234abcd" / "proposal.md").read_text()
    assert "applied_by: special_user" in content


def test_apply_calls_clock_once(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_approved(
        proposals, digest="to-be-overwritten", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    res = load_proposal_directory(
        proposals / "prop-20260714T120000Z-1234abcd", proposals_root=proposals
    )
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )
    _create_approved(proposals, digest=actual_digest, proposal_id="prop-20260714T120000Z-1234abcd")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    clock = MockClock()
    apply_proposal_tool(
        vault_root=vault,
        request=ApplyProposalRequest(proposal_id="prop-20260714T120000Z-1234abcd"),
        authorizer=authorizer,
        clock_fn=clock,
    )
    assert clock.calls == 1


def test_apply_rejects_unapproved_proposal(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_draft(proposals, proposal_id="prop-20260714T120000Z-1234abcd")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    with pytest.raises(ToolConflictError, match="Cannot apply from draft"):
        apply_proposal_tool(
            vault_root=vault,
            request=ApplyProposalRequest(proposal_id="prop-20260714T120000Z-1234abcd"),
            authorizer=authorizer,
            clock_fn=MockClock(),
        )


def test_apply_changed_content_after_authorization_is_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_approved(
        proposals, digest="to-be-overwritten", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    res = load_proposal_directory(
        proposals / "prop-20260714T120000Z-1234abcd", proposals_root=proposals
    )
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )
    _create_approved(proposals, digest=actual_digest, proposal_id="prop-20260714T120000Z-1234abcd")

    authorizer = MutatingAuthorizer(proposals)

    with pytest.raises(ToolExecutionError):
        apply_proposal_tool(
            vault_root=vault,
            request=ApplyProposalRequest(proposal_id="prop-20260714T120000Z-1234abcd"),
            authorizer=authorizer,
            clock_fn=MockClock(),
        )


def test_apply_target_conflict_maps_to_conflict(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"

    prop_dir = proposals / "prop-20260714T120000Z-1234abcd"
    prop_dir.mkdir(parents=True, exist_ok=True)
    (prop_dir / "proposal.md").write_text("""---
id: prop-20260714T120000Z-1234abcd
schema_version: 1
patch_schema_version: 1
lifecycle_schema_version: 1
title: Test Proposal
description: desc
risk: low
status: approved
created_at: "2020-01-01T12:00:00Z"
created_by: user1
submitted_at: "2020-01-01T12:00:00Z"
submitted_by: user1
approved_at: "2020-01-01T12:00:00Z"
approved_by: user1
review_digest: to-be-overwritten
---
# Proposal""")
    (prop_dir / "patches.json").write_bytes(
        (
            json.dumps(
                {
                    "operations": [
                        {
                            "op": "create_file",
                            "id": "op-1",
                            "target_path": "test.txt",
                            "expected_target_state": "absent",
                            "new_content": "hello",
                        }
                    ],
                    "proposal_id": "prop-20260714T120000Z-1234abcd",
                    "schema_version": 1,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )

    res = load_proposal_directory(prop_dir, proposals_root=proposals)
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )

    (prop_dir / "proposal.md").write_text(f"""---
id: prop-20260714T120000Z-1234abcd
schema_version: 1
patch_schema_version: 1
lifecycle_schema_version: 1
title: Test Proposal
description: desc
risk: low
status: approved
created_at: "2020-01-01T12:00:00Z"
created_by: user1
submitted_at: "2020-01-01T12:00:00Z"
submitted_by: user1
approved_at: "2020-01-01T12:00:00Z"
approved_by: user1
review_digest: {actual_digest}
---
# Proposal""")

    def mock_apply_proposal(*args, **kwargs):
        from lifeos.proposals.application import ApplicationError, ApplicationErrorCode

        raise ApplicationError("Target Conflict", None, code=ApplicationErrorCode.TARGET_CONFLICT)

    monkeypatch.setattr("lifeos.facade.consequential_tools.apply_proposal", mock_apply_proposal)
    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    with pytest.raises(ToolConflictError, match="Conflict during application"):
        apply_proposal_tool(
            vault_root=vault,
            request=ApplyProposalRequest(proposal_id="prop-20260714T120000Z-1234abcd"),
            authorizer=authorizer,
            clock_fn=MockClock(),
        )


def test_apply_ownership_conflict_maps_to_conflict() -> None:
    from lifeos.facade.consequential_tools import _map_application_error
    from lifeos.proposals.application import ApplicationError, ApplicationErrorCode

    mapped = _map_application_error(
        ApplicationError(
            "ownership conflict",
            None,  # type: ignore[arg-type]
            code=ApplicationErrorCode.OWNERSHIP_CONFLICT,
        )
    )

    assert isinstance(mapped, ToolConflictError)
    assert "Conflict during application" in str(mapped)


def test_apply_io_failure_maps_to_execution_error(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"

    prop_dir = proposals / "prop-20260714T120000Z-1234abcd"
    prop_dir.mkdir(parents=True, exist_ok=True)
    (prop_dir / "proposal.md").write_text("""---
id: prop-20260714T120000Z-1234abcd
schema_version: 1
patch_schema_version: 1
lifecycle_schema_version: 1
title: Test Proposal
description: desc
risk: low
status: approved
created_at: "2020-01-01T12:00:00Z"
created_by: user1
submitted_at: "2020-01-01T12:00:00Z"
submitted_by: user1
approved_at: "2020-01-01T12:00:00Z"
approved_by: user1
review_digest: to-be-overwritten
---
# Proposal""")
    (prop_dir / "patches.json").write_bytes(
        (
            json.dumps(
                {
                    "operations": [
                        {
                            "op": "create_file",
                            "id": "op-1",
                            "target_path": "test.txt",
                            "expected_target_state": "absent",
                            "new_content": "hello",
                        }
                    ],
                    "proposal_id": "prop-20260714T120000Z-1234abcd",
                    "schema_version": 1,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )

    res = load_proposal_directory(prop_dir, proposals_root=proposals)
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )

    (prop_dir / "proposal.md").write_text(f"""---
id: prop-20260714T120000Z-1234abcd
schema_version: 1
patch_schema_version: 1
lifecycle_schema_version: 1
title: Test Proposal
description: desc
risk: low
status: approved
created_at: "2020-01-01T12:00:00Z"
created_by: user1
submitted_at: "2020-01-01T12:00:00Z"
submitted_by: user1
approved_at: "2020-01-01T12:00:00Z"
approved_by: user1
review_digest: {actual_digest}
---
# Proposal""")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    def fail_staging(*_args, **_kwargs):
        raise OSError("Injected IO error during staging")

    monkeypatch.setattr(
        "lifeos.proposals.application.create_staging_file",
        fail_staging,
    )

    authorizer = MockAuthorizer("userX")
    with pytest.raises(ToolExecutionError) as exc_info:
        apply_proposal_tool(
            vault_root=vault,
            request=ApplyProposalRequest(proposal_id="prop-20260714T120000Z-1234abcd"),
            authorizer=authorizer,
            clock_fn=MockClock(),
        )

    cause = exc_info.value.__cause__
    from lifeos.proposals.application import ApplicationError, ApplicationErrorCode

    assert isinstance(cause, ApplicationError)
    assert cause.code == ApplicationErrorCode.IO_ERROR
    assert isinstance(cause.__cause__, OSError)

    assert not (vault / "test.txt").exists()


def test_apply_failure_does_not_report_applied(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"
    _create_approved(
        proposals, digest="to-be-overwritten", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    res = load_proposal_directory(
        proposals / "prop-20260714T120000Z-1234abcd", proposals_root=proposals
    )
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )
    _create_approved(proposals, digest=actual_digest, proposal_id="prop-20260714T120000Z-1234abcd")

    def mock_apply_proposal(*args, **kwargs):
        from lifeos.proposals.application import ApplicationError, ApplicationErrorCode

        raise ApplicationError("IO Failed", None, code=ApplicationErrorCode.IO_ERROR)

    monkeypatch.setattr("lifeos.facade.consequential_tools.apply_proposal", mock_apply_proposal)

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    with pytest.raises(ToolExecutionError):
        apply_proposal_tool(
            vault_root=vault,
            request=ApplyProposalRequest(proposal_id="prop-20260714T120000Z-1234abcd"),
            authorizer=authorizer,
            clock_fn=MockClock(),
        )

    # Assert not applied
    content = (proposals / "prop-20260714T120000Z-1234abcd" / "proposal.md").read_text()
    assert "status: applied" not in content


def test_apply_returns_vault_relative_changed_paths(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    proposals = vault / "proposals"

    prop_dir = proposals / "prop-20260714T120000Z-1234abcd"
    prop_dir.mkdir(parents=True, exist_ok=True)
    (prop_dir / "proposal.md").write_text("""---
id: prop-20260714T120000Z-1234abcd
schema_version: 1
patch_schema_version: 1
lifecycle_schema_version: 1
title: Test Proposal
description: desc
risk: low
status: approved
created_at: "2020-01-01T12:00:00Z"
created_by: user1
submitted_at: "2020-01-01T12:00:00Z"
submitted_by: user1
approved_at: "2020-01-01T12:00:00Z"
approved_by: user1
review_digest: to-be-overwritten
---
# Proposal""")
    (prop_dir / "patches.json").write_bytes(
        (
            json.dumps(
                {
                    "operations": [
                        {
                            "op": "create_file",
                            "id": "op-1",
                            "target_path": "test.txt",
                            "expected_target_state": "absent",
                            "new_content": "hello",
                        }
                    ],
                    "proposal_id": "prop-20260714T120000Z-1234abcd",
                    "schema_version": 1,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )

    res = load_proposal_directory(prop_dir, proposals_root=proposals)
    actual_digest = compute_review_digest(
        res.proposal.metadata, res.proposal.body, res.proposal.patch_document
    )

    (prop_dir / "proposal.md").write_text(f"""---
id: prop-20260714T120000Z-1234abcd
schema_version: 1
patch_schema_version: 1
lifecycle_schema_version: 1
title: Test Proposal
description: desc
risk: low
status: approved
created_at: "2020-01-01T12:00:00Z"
created_by: user1
submitted_at: "2020-01-01T12:00:00Z"
submitted_by: user1
approved_at: "2020-01-01T12:00:00Z"
approved_by: user1
review_digest: {actual_digest}
---
# Proposal""")

    (vault / "system").mkdir(parents=True, exist_ok=True)
    (vault / "system" / "generated-ownership.json").write_text(
        '{"schema_version": 1, "owned_files": {}}'
    )

    authorizer = MockAuthorizer("userX")
    result = apply_proposal_tool(
        vault_root=vault,
        request=ApplyProposalRequest(proposal_id="prop-20260714T120000Z-1234abcd"),
        authorizer=authorizer,
        clock_fn=MockClock(),
    )

    assert result.status == "applied"
    assert result.changed_paths
    assert all(isinstance(path, str) for path in result.changed_paths)
    assert all(not Path(path).is_absolute() for path in result.changed_paths)
    assert all("\\" not in path for path in result.changed_paths)
    assert all(str(vault) not in path for path in result.changed_paths)
    assert "test.txt" in result.changed_paths

    assert (vault / "test.txt").exists()
    assert (vault / "test.txt").read_text() == "hello"


def test_recovery_required_maps_to_dedicated_facade_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from lifeos.facade.consequential_tools import _map_application_error
    from lifeos.facade.errors import ToolRecoveryRequiredError
    from lifeos.proposals.application import ApplicationError, ApplicationErrorCode

    error = ApplicationError(
        "sensitive recovery detail",
        None,  # type: ignore[arg-type]
        code=ApplicationErrorCode.RECOVERY_REQUIRED,
    )
    mapped = _map_application_error(error)

    assert isinstance(mapped, ToolRecoveryRequiredError)
    assert str(mapped) == "Recovery is required before application can continue"
    assert "sensitive" not in str(mapped)


def test_proposal_loader_oserror_maps_to_execution_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_load(*_args, **_kwargs):
        raise OSError("injected loader failure")

    monkeypatch.setattr(
        "lifeos.facade.consequential_tools.load_proposal_directory",
        fail_load,
    )

    with pytest.raises(ToolExecutionError, match="Could not load proposal") as exc_info:
        submit_proposal_tool(
            vault_root=tmp_path / "vault",
            request=SubmitProposalRequest("prop-20260714T120000Z-1234abcd"),
            authorizer=MockAuthorizer(),
        )

    assert isinstance(exc_info.value.__cause__, OSError)
