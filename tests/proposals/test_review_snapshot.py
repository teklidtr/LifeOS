import hashlib
import json
from pathlib import Path

import pytest

from lifeos.proposals.patches import (
    CreateGeneratedFileV2,
    PatchDocumentV2,
    PatchHumanFile,
    ReleaseGeneratedOwnershipV2,
    ReplaceGeneratedFileV2,
    ReplaceManagedBlock,
)
from lifeos.proposals.review_snapshot import (
    ReviewSnapshotError,
    build_review_snapshot,
    parse_review_snapshot_bytes,
    serialize_review_snapshot_bytes,
)


PROPOSAL_ID = "prop-20260822T190000Z-a1b2c3d4"


def _hash(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def test_snapshot_covers_all_operation_types_in_order(tmp_path: Path) -> None:
    generated = "# Generated\n\nOld value.\n"
    human = "old\n"
    managed = (
        "# Managed\n\n<!-- lifeos:managed:start summary -->\n"
        "Old summary.\n<!-- lifeos:managed:end summary -->\n"
    )
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/generated.md").write_text(generated, encoding="utf-8")
    (tmp_path / "wiki/human.md").write_text(human, encoding="utf-8")
    (tmp_path / "wiki/managed.md").write_text(managed, encoding="utf-8")
    manifest = tmp_path / "system/generated-ownership.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "owned_files": {
                    "wiki/orphan.md": {
                        "generator_id": "lifeos.test",
                        "generator_version": "1",
                        "content_hash": "a" * 64,
                        "created_at": "2026-08-22T10:00:00Z",
                        "updated_at": "2026-08-22T11:00:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    document = PatchDocumentV2(
        2,
        PROPOSAL_ID,
        (
            CreateGeneratedFileV2(
                "op-create", "wiki/new.md", "absent", "lifeos.test", "1", "# New\n"
            ),
            PatchHumanFile(
                "op-human",
                "wiki/human.md",
                _hash(human),
                "@@ -1 +1 @@\n-old\n+new\n",
            ),
            ReplaceGeneratedFileV2(
                "op-generated",
                "wiki/generated.md",
                _hash(generated),
                "lifeos.test",
                "2",
                "# Generated\n\nNew value.\n",
            ),
            ReplaceManagedBlock(
                "op-managed",
                "wiki/managed.md",
                _hash(managed),
                "summary",
                "New summary.\n",
            ),
            ReleaseGeneratedOwnershipV2(
                "op-release",
                "wiki/orphan.md",
                "sha256:" + "a" * 64,
                "lifeos.test",
                "1",
                "2026-08-22T10:00:00Z",
                "2026-08-22T11:00:00Z",
            ),
        ),
    )

    snapshot = build_review_snapshot(vault_root=tmp_path, patch_document=document)

    assert [item.operation_type for item in snapshot.operations] == [
        "create_generated_file",
        "patch_human_file",
        "replace_generated_file",
        "replace_managed_block",
        "release_generated_ownership",
    ]
    assert "+# New" in snapshot.operations[0].unified_diff
    assert "-old" in snapshot.operations[1].unified_diff
    assert "-Old value." in snapshot.operations[2].unified_diff
    assert "+New summary." in snapshot.operations[3].unified_diff
    assert '-    "wiki/orphan.md": {' in snapshot.operations[4].unified_diff


def test_snapshot_remains_parseable_after_target_and_manifest_change(tmp_path: Path) -> None:
    original = "old\n"
    target = tmp_path / "wiki/generated.md"
    target.parent.mkdir()
    target.write_text(original, encoding="utf-8")
    document = PatchDocumentV2(
        2,
        PROPOSAL_ID,
        (
            ReplaceGeneratedFileV2(
                "op-replace",
                "wiki/generated.md",
                _hash(original),
                "lifeos.test",
                "2",
                "new\n",
            ),
        ),
    )
    frozen = serialize_review_snapshot_bytes(
        build_review_snapshot(vault_root=tmp_path, patch_document=document)
    )

    target.unlink()
    parsed = parse_review_snapshot_bytes(frozen, patch_document=document)

    assert "-old" in parsed.operations[0].unified_diff
    assert "+new" in parsed.operations[0].unified_diff


def test_snapshot_tampering_and_operation_mismatch_fail_closed(tmp_path: Path) -> None:
    document = PatchDocumentV2(
        2,
        PROPOSAL_ID,
        (
            CreateGeneratedFileV2(
                "op-create", "wiki/new.md", "absent", "lifeos.test", "1", "new"
            ),
        ),
    )
    frozen = serialize_review_snapshot_bytes(
        build_review_snapshot(vault_root=tmp_path, patch_document=document)
    )
    data = json.loads(frozen)
    data["operations"][0]["operation_id"] = "op-other"
    tampered = (
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    with pytest.raises(ReviewSnapshotError) as error:
        parse_review_snapshot_bytes(tampered, patch_document=document)

    assert error.value.code == "operation_identity_mismatch"


def test_human_patch_snapshot_requires_current_reviewed_target(tmp_path: Path) -> None:
    target = tmp_path / "wiki/human.md"
    target.parent.mkdir(parents=True)
    original = "# Human\n\nOld\n"
    target.write_text(original, encoding="utf-8")
    operation = PatchHumanFile(
        "op-human",
        "wiki/human.md",
        _hash(original),
        "@@ -3 +3 @@\n-Old\n+New\n",
    )
    document = PatchDocumentV2(2, PROPOSAL_ID, (operation,))
    target.write_text("# Human\n\nChanged elsewhere\n", encoding="utf-8")

    with pytest.raises(ReviewSnapshotError) as error:
        build_review_snapshot(vault_root=tmp_path, patch_document=document)

    assert error.value.code == "stale_base_hash"
