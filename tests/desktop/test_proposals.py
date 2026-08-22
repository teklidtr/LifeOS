import hashlib
import json
from pathlib import Path

import pytest

from lifeos.desktop import DesktopProposalService
from lifeos.facade.authorization import AuthorizationDeniedError, ConsequentialAction, ConsequentialAuthorizationRequest
from lifeos.proposals.loader import load_proposal_directory


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

    loaded = load_proposal_directory(
        proposal_dir,
        proposals_root=tmp_path / "proposals",
    )
    assert loaded.proposal is not None, loaded.findings

    inspection = DesktopProposalService(vault_root=tmp_path, actor_id="me").inspect(
        proposal_id
    )

    assert inspection.created_at == "2026-08-22T12:23:09Z"
    assert inspection.to_dict()["created_at"] == "2026-08-22T12:23:09Z"


def test_inspection_exposes_created_file_and_human_patch_diffs(tmp_path: Path) -> None:
    proposal_id = "prop-20260822T141239Z-01726d46"
    proposal_dir = tmp_path / "proposals" / proposal_id
    proposal_dir.mkdir(parents=True)
    target_path = "wiki/ilk-yardim.md"
    target = tmp_path / target_path
    target.parent.mkdir(parents=True)
    original = "# İlk Yardım\n\n## Ekipman notları\n\nEski not.\n"
    target.write_text(original, encoding="utf-8")
    base_hash = f"sha256:{hashlib.sha256(original.encode('utf-8')).hexdigest()}"
    proposal_dir.joinpath("proposal.md").write_text(
        "\n".join(
            (
                "---",
                f'id: "{proposal_id}"',
                'title: "Compound proposal"',
                'description: "Shows two diffs"',
                "status: draft",
                "risk: medium",
                'created_at: "2026-08-22T14:12:39Z"',
                'created_by: "test"',
                "related_goals: []",
                "related_sources: []",
                "extensions: {}",
                "schema_version: 1",
                "patch_schema_version: 2",
                "---",
                "Body",
                "",
            )
        ),
        encoding="utf-8",
    )
    proposal_dir.joinpath("patches.json").write_text(
        json.dumps(
            {
                "operations": [
                    {
                        "expected_target_state": "absent",
                        "generator_id": "lifeos.test",
                        "generator_version": "1",
                        "id": "op-create-page",
                        "new_content": "# Yeni sayfa\n\nYeni içerik.\n",
                        "op": "create_generated_file",
                        "target_path": "wiki/yeni-sayfa.md",
                    },
                    {
                        "base_hash": base_hash,
                        "id": "op-update-section",
                        "op": "patch_human_file",
                        "target_path": target_path,
                        "unified_diff": (
                            "@@ -3,3 +3,3 @@\n"
                            " ## Ekipman notları\n"
                            " \n"
                            "-Eski not.\n"
                            "+Yeni not.\n"
                        ),
                    },
                ],
                "proposal_id": proposal_id,
                "schema_version": 2,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = load_proposal_directory(
        proposal_dir,
        proposals_root=tmp_path / "proposals",
    )
    assert loaded.proposal is not None, loaded.findings

    inspection = DesktopProposalService(vault_root=tmp_path, actor_id="me").inspect(
        proposal_id
    )

    assert len(inspection.operations) == 2
    created, patched = inspection.operations
    assert created.operation_type == "create_generated_file"
    assert created.target_path == "wiki/yeni-sayfa.md"
    assert "--- /dev/null" in created.unified_diff
    assert "+# Yeni sayfa" in created.unified_diff
    assert patched.operation_type == "patch_human_file"
    assert "--- a/wiki/ilk-yardim.md" in patched.unified_diff
    assert "-Eski not." in patched.unified_diff
    assert "+Yeni not." in patched.unified_diff
    assert patched.preview_error is None


def test_stale_replacement_diff_degrades_without_hiding_proposal(tmp_path: Path) -> None:
    proposal_id = "prop-20260822T150000Z-1234abcd"
    proposal_dir = tmp_path / "proposals" / proposal_id
    proposal_dir.mkdir(parents=True)
    target = tmp_path / "wiki/generated.md"
    target.parent.mkdir(parents=True)
    target.write_text("Current content\n", encoding="utf-8")
    proposal_dir.joinpath("proposal.md").write_text(
        "\n".join(
            (
                "---",
                f'id: "{proposal_id}"',
                'title: "Stale replacement"',
                'description: "Preview should fail safely"',
                "status: draft",
                "risk: low",
                'created_at: "2026-08-22T15:00:00Z"',
                'created_by: "test"',
                "related_goals: []",
                "related_sources: []",
                "extensions: {}",
                "schema_version: 1",
                "patch_schema_version: 2",
                "---",
                "Body",
                "",
            )
        ),
        encoding="utf-8",
    )
    proposal_dir.joinpath("patches.json").write_text(
        json.dumps(
            {
                "operations": [
                    {
                        "base_hash": f"sha256:{'0' * 64}",
                        "expected_generator_id": "lifeos.test",
                        "generator_version": "1",
                        "id": "op-replace-page",
                        "new_content": "Replacement content\n",
                        "op": "replace_generated_file",
                        "target_path": "wiki/generated.md",
                    }
                ],
                "proposal_id": proposal_id,
                "schema_version": 2,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    service = DesktopProposalService(vault_root=tmp_path, actor_id="me")
    inspection = service.inspect(proposal_id)

    assert inspection.operations[0].unified_diff == ""
    assert inspection.operations[0].preview_error == (
        "Diff preview unavailable: target content no longer matches the proposal base hash"
    )
    assert [proposal.proposal_id for proposal in service.list()] == [proposal_id]
