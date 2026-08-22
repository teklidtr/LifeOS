import json
from pathlib import Path

import pytest

from lifeos.desktop import DesktopProposalService
from lifeos.facade.authorization import AuthorizationDeniedError, ConsequentialAction, ConsequentialAuthorizationRequest


def test_one_use_confirmation_is_bound_to_exact_action(tmp_path: Path) -> None:
    service=DesktopProposalService(vault_root=tmp_path,actor_id="me")
    token=service.authorizer.issue(action=ConsequentialAction.SUBMIT,proposal_id="p",review_digest=None)
    service.authorizer.activate(token)
    principal=service.authorizer.authorize(ConsequentialAuthorizationRequest(ConsequentialAction.SUBMIT,"p",None))
    assert principal.actor_id=="me"
    with pytest.raises(AuthorizationDeniedError):
        service.authorizer.authorize(ConsequentialAuthorizationRequest(ConsequentialAction.SUBMIT,"p",None))


def test_confirmation_cannot_be_reused_for_other_proposal(tmp_path: Path) -> None:
    service=DesktopProposalService(vault_root=tmp_path,actor_id="me")
    token=service.authorizer.issue(action=ConsequentialAction.APPLY,proposal_id="p",review_digest="d")
    service.authorizer.activate(token)
    with pytest.raises(AuthorizationDeniedError):
        service.authorizer.authorize(ConsequentialAuthorizationRequest(ConsequentialAction.APPLY,"other","d"))


def test_inspection_exposes_canonical_created_at(tmp_path: Path) -> None:
    proposal_id = "prop-20260822T122309Z-de27813d"
    proposal_dir = tmp_path / "proposals" / proposal_id
    proposal_dir.mkdir(parents=True)
    proposal_dir.joinpath("proposal.md").write_text(
        "\n".join(
            (
                "---",
                f'id: "{proposal_id}"',
                'title: "Dated proposal"',
                'description: "Shows its creation time"',
                "status: draft",
                "risk: low",
                'created_at: "2026-08-22T12:23:09Z"',
                'created_by: "test"',
                "related_goals: []",
                "related_sources: []",
                "extensions: {}",
                "schema_version: 1",
                "patch_schema_version: 1",
                "---",
                "Body",
                "",
            )
        ),
        encoding="utf-8",
    )
    proposal_dir.joinpath("patches.json").write_text(
        json.dumps(
            {"operations": [], "proposal_id": proposal_id, "schema_version": 1},
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    inspection = DesktopProposalService(vault_root=tmp_path, actor_id="me").inspect(
        proposal_id
    )

    assert inspection.created_at == "2026-08-22T12:23:09Z"
    assert inspection.to_dict()["created_at"] == "2026-08-22T12:23:09Z"
