from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import lifeos.desktop.proposals as desktop_proposals
from lifeos.desktop import DesktopProposalService


def test_legacy_runtime_preview_rejects_before_live_target_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    runtime = vault / "wiki" / "runtime-node"
    runtime.mkdir(parents=True)
    target_path = "wiki/runtime-node/export.md"
    target = vault / target_path
    content = "# Derived export\n\nProtected-derived bytes must not enter preview.\n"
    target.write_text(content, encoding="utf-8")

    proposal_id = "prop-20260825T080000Z-1234abcd"
    proposal_dir = vault / "proposals" / proposal_id
    proposal_dir.mkdir(parents=True)
    proposal_dir.joinpath("proposal.md").write_text(
        "\n".join(
            (
                "---",
                f'id: "{proposal_id}"',
                'title: "Legacy runtime preview"',
                'description: "Must reject live runtime inspection"',
                "status: draft",
                "risk: medium",
                'created_at: "2026-08-25T08:00:00Z"',
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
    base_hash = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
    proposal_dir.joinpath("patches.json").write_text(
        json.dumps(
            {
                "operations": [
                    {
                        "base_hash": base_hash,
                        "id": "op-runtime-update",
                        "op": "patch_human_file",
                        "target_path": target_path,
                        "unified_diff": "@@ -1 +1 @@\n-# Derived export\n+# Changed\n",
                    }
                ],
                "proposal_id": proposal_id,
                "schema_version": 1,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    def fail_live_preview(*args: object, **kwargs: object) -> str:
        pytest.fail("runtime target reached live preview reconstruction")

    monkeypatch.setattr(desktop_proposals, "operation_unified_diff", fail_live_preview)
    service = DesktopProposalService(
        vault_root=vault,
        actor_id="desktop-user",
        identity_runtime_dir=runtime,
    )

    inspection = service.inspect(proposal_id)

    assert inspection.operations[0].unified_diff == ""
    assert inspection.operations[0].preview_error == (
        "Diff preview unavailable: target is inside configured runtime state"
    )
    assert inspection.operations[0].preview_source == "legacy_live"
