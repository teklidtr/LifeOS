import json
import os
from pathlib import Path


from lifeos.ownership import DEFAULT_OWNERSHIP_MANIFEST_PATH
from lifeos.proposals import (
    LoadedProposal,
    PatchDocument,
    PatchOperation,
    CreateGeneratedFile,
    CreateFile,
    PatchHumanFile,
    ReplaceGeneratedFile,
    ReplaceManagedBlock,
    ProposalMetadata,
    preflight_proposal,
)

VALID_PROP_ID = "prop-20260713T000000Z-abcdef12"

def _make_dummy_proposal(operations: list[PatchOperation]) -> LoadedProposal:
    return LoadedProposal(
        proposal_dir=VALID_PROP_ID,
        proposal_path=f"{VALID_PROP_ID}/proposal.md",
        patches_path=f"{VALID_PROP_ID}/patches.json",
        proposal_source_hash="sha256:dummy",
        patches_source_hash="sha256:dummy",
        metadata=ProposalMetadata(
            id=VALID_PROP_ID,
            schema_version=1,
            patch_schema_version=1,
            lifecycle_schema_version=None,
            title="Test Proposal",
            description="A test proposal.",
            status="pending",
            risk="low",
            created_at="2026-07-13T00:00:00+00:00",
            created_by="agent",
            submitted_at=None,
            submitted_by=None,
            review_digest=None,
            approved_at=None,
            approved_by=None,
            rejected_at=None,
            rejected_by=None,
            rejection_reason=None,
            applied_at=None,
            applied_by=None,
            related_goals=[],
            related_sources=[],
            extensions={},
        ),
        patch_document=PatchDocument(1, VALID_PROP_ID, tuple(operations)),
        body="",
    )


def test_state_aggregation_priority(tmp_path: Path) -> None:
    # invalid > stale > valid
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')

    # valid
    op1 = CreateFile(id="op-1", target_path="a.txt", expected_target_state="absent", new_content="content")
    # stale (target exists)
    op2 = CreateFile(id="op-2", target_path="b.txt", expected_target_state="absent", new_content="content")
    # invalid (target is directory)
    op3 = CreateFile(id="op-3", target_path="c", expected_target_state="absent", new_content="content")

    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "c").mkdir()

    prop = _make_dummy_proposal([op1, op2, op3])
    res = preflight_proposal(prop, vault_root=tmp_path)

    assert res.operations[0].state == "valid"
    assert res.operations[1].state == "stale"
    assert res.operations[2].state == "invalid"

    assert res.state == "invalid"


def test_operation_order_preservation(tmp_path: Path) -> None:
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')

    ops = [
        CreateFile(id="op-3", target_path="a.txt", expected_target_state="absent", new_content="content"),
        CreateFile(id="op-1", target_path="b.txt", expected_target_state="absent", new_content="content"),
        CreateFile(id="op-2", target_path="c.txt", expected_target_state="absent", new_content="content"),
    ]
    prop = _make_dummy_proposal(ops)
    res = preflight_proposal(prop, vault_root=tmp_path)

    assert len(res.operations) == 3
    assert res.operations[0].operation_id == "op-3"
    assert res.operations[1].operation_id == "op-1"
    assert res.operations[2].operation_id == "op-2"


def test_empty_proposal_no_manifest_read(tmp_path: Path) -> None:
    prop = _make_dummy_proposal([])
    res = preflight_proposal(prop, vault_root=tmp_path)
    assert res.state == "valid"
    assert not (tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH).exists()


def test_failed_manifest_prevents_target_reads(tmp_path: Path) -> None:
    # Manifest missing
    op1 = PatchHumanFile(id="op-1", target_path="a.txt", base_hash="sha256:" + "0"*64, unified_diff="diff")
    prop = _make_dummy_proposal([op1])
    res = preflight_proposal(prop, vault_root=tmp_path)

    assert res.state == "invalid"
    assert len(res.findings) == 1
    assert res.findings[0].code == "manifest_missing"
    assert res.operations[0].state == "invalid"
    assert res.operations[0].findings[0].code == "aborted"

    # We didn't even check a.txt's existence/read it


def test_canonical_ownership_rejection(tmp_path: Path) -> None:
    op1 = PatchHumanFile(id="op-1", target_path=str(DEFAULT_OWNERSHIP_MANIFEST_PATH), base_hash="sha256:" + "0"*64, unified_diff="diff")
    op2 = CreateFile(id="op-2", target_path="a.txt", expected_target_state="absent", new_content="content")
    prop = _make_dummy_proposal([op1, op2])
    res = preflight_proposal(prop, vault_root=tmp_path)

    assert res.state == "invalid"
    assert res.operations[0].state == "invalid"
    assert res.operations[0].findings[0].code == "reserved_authorization_target"

    assert res.operations[1].state == "invalid"
    assert res.operations[1].findings[0].code == "aborted"


def test_directory_and_special_create_targets(tmp_path: Path) -> None:
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')

    (tmp_path / "dir1").mkdir()
    os.mkfifo(tmp_path / "fifo1")

    op1 = CreateFile(id="op-1", target_path="dir1", expected_target_state="absent", new_content="content")
    op2 = CreateFile(id="op-2", target_path="fifo1", expected_target_state="absent", new_content="content")
    prop = _make_dummy_proposal([op1, op2])
    res = preflight_proposal(prop, vault_root=tmp_path)

    assert res.operations[0].state == "invalid"
    assert res.operations[0].findings[0].code == "invalid_target_type"

    assert res.operations[1].state == "invalid"
    assert res.operations[1].findings[0].code == "invalid_target_type"


def test_invalid_utf8_human_file(tmp_path: Path) -> None:
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')

    (tmp_path / "bad.txt").write_bytes(b"\xff\xfe")

    op1 = PatchHumanFile(id="op-1", target_path="bad.txt", base_hash="sha256:" + "0"*64, unified_diff="diff")
    prop = _make_dummy_proposal([op1])
    res = preflight_proposal(prop, vault_root=tmp_path)

    assert res.operations[0].state == "invalid"
    assert res.operations[0].findings[0].code == "invalid_utf8"


def test_ownership_raw_digest_vs_prefixed_patch_hash(tmp_path: Path) -> None:
    import hashlib
    content = b"gencontent"
    raw_digest = hashlib.sha256(content).hexdigest()

    manifest_json = {
        "schema_version": 1,
        "owned_files": {
            "gen.txt": {
                "generator_id": "gen1",
                "generator_version": "1.0",
                "content_hash": raw_digest,
                "created_at": "2026-07-13T00:00:00+00:00",
                "updated_at": "2026-07-13T00:00:00+00:00"
            }
        }
    }
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_json))

    (tmp_path / "gen.txt").write_bytes(content)

    # Correct prefix
    op1 = ReplaceGeneratedFile(
        id="op-1",
        target_path="gen.txt",
        expected_generator_id="gen1",
        base_hash=f"sha256:{raw_digest}",
        new_content="content"
    )
    prop = _make_dummy_proposal([op1])
    res = preflight_proposal(prop, vault_root=tmp_path)
    assert res.operations[0].state == "valid"

    # Stale
    op2 = ReplaceGeneratedFile(
        id="op-2",
        target_path="gen.txt",
        expected_generator_id="gen1",
        base_hash=f"sha256:{'f'*64}",
        new_content="content"
    )
    prop = _make_dummy_proposal([op2])
    res = preflight_proposal(prop, vault_root=tmp_path)
    assert res.operations[0].state == "stale"

    # Invalid (manifest mismatch, we manually change file without updating manifest)
    (tmp_path / "gen.txt").write_bytes(b"hacked")
    prop = _make_dummy_proposal([op1])
    res = preflight_proposal(prop, vault_root=tmp_path)
    assert res.operations[0].state == "invalid"
    assert res.operations[0].findings[0].code == "unauthorized_modification"


def test_inspection_limits(tmp_path: Path) -> None:
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')

    # Create file exact size
    content = b"a" * 200
    (tmp_path / "exact.txt").write_bytes(content)
    # Create file oversized by 1 byte
    (tmp_path / "over.txt").write_bytes(content + b"b")

    op1 = PatchHumanFile(id="op-1", target_path="exact.txt", base_hash="sha256:" + "0"*64, unified_diff="diff")
    prop = _make_dummy_proposal([op1])
    res = preflight_proposal(prop, vault_root=tmp_path, max_inspection_bytes=200)
    # State is stale because base_hash is missing, but it wasn't rejected for size!
    assert res.operations[0].state == "stale"

    op2 = PatchHumanFile(id="op-2", target_path="over.txt", base_hash="sha256:" + "0"*64, unified_diff="diff")
    prop = _make_dummy_proposal([op2])
    res = preflight_proposal(prop, vault_root=tmp_path, max_inspection_bytes=200)
    assert res.operations[0].state == "invalid"
    assert res.operations[0].findings[0].code == "target_too_large_for_inspection"


def test_replace_generated_ignores_size_limits(tmp_path: Path) -> None:
    import hashlib
    import os
    from unittest.mock import patch

    content = b"a" * 600
    raw_digest = hashlib.sha256(content).hexdigest()

    manifest_json = {
        "schema_version": 1,
        "owned_files": {
            "gen.txt": {
                "generator_id": "gen1",
                "generator_version": "1.0",
                "content_hash": raw_digest,
                "created_at": "2026-07-13T00:00:00+00:00",
                "updated_at": "2026-07-13T00:00:00+00:00"
            }
        }
    }
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_json))

    (tmp_path / "gen.txt").write_bytes(content)

    # 1. Valid (large target)
    op1 = ReplaceGeneratedFile(
        id="op-1",
        target_path="gen.txt",
        expected_generator_id="gen1",
        base_hash=f"sha256:{raw_digest}",
        new_content="content"
    )
    prop = _make_dummy_proposal([op1])

    # Prove that the file is streamed by wrapping os.read
    original_os_read = os.read
    read_calls = []
    def mock_os_read(fd: int, n: int) -> bytes:
        read_calls.append(n)
        return original_os_read(fd, n)

    with patch("os.read", side_effect=mock_os_read):
        res = preflight_proposal(prop, vault_root=tmp_path, max_inspection_bytes=500)

    assert res.operations[0].state == "valid"
    # Ensure it was called with fixed chunks (e.g. 65536) and not one massive buffer
    assert any(n == 65536 for n in read_calls)

    # 2. Stale (patch base hash differs)
    op2 = ReplaceGeneratedFile(
        id="op-2",
        target_path="gen.txt",
        expected_generator_id="gen1",
        base_hash=f"sha256:{'f'*64}",
        new_content="content"
    )
    prop2 = _make_dummy_proposal([op2])
    res2 = preflight_proposal(prop2, vault_root=tmp_path, max_inspection_bytes=500)
    assert res2.operations[0].state == "stale"

    # 3. Invalid (ownership hash differs from file content)
    (tmp_path / "gen.txt").write_bytes(b"hacked_content")
    res3 = preflight_proposal(prop, vault_root=tmp_path, max_inspection_bytes=500)
    assert res3.operations[0].state == "invalid"
    assert res3.operations[0].findings[0].code == "unauthorized_modification"


def test_replace_managed_block_boundaries(tmp_path: Path) -> None:
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')

    import hashlib
    original_text = "human\n<!-- lifeos:managed:start foo -->\nold\n<!-- lifeos:managed:end foo -->\nhuman"
    original_bytes = original_text.encode("utf-8")
    original_hash = f"sha256:{hashlib.sha256(original_bytes).hexdigest()}"
    (tmp_path / "block.md").write_bytes(original_bytes)

    # 1. Valid replacement
    op1 = ReplaceManagedBlock(
        id="op-1",
        target_path="block.md",
        block_name="foo",
        base_hash=original_hash,
        new_content="new\nmulti"
    )
    prop = _make_dummy_proposal([op1])
    res = preflight_proposal(prop, vault_root=tmp_path)
    assert res.operations[0].state == "valid"

    # 2. Injection rejection
    op2 = ReplaceManagedBlock(
        id="op-2",
        target_path="block.md",
        block_name="foo",
        base_hash=original_hash,
        new_content="new\n<!-- lifeos:managed"
    )
    prop = _make_dummy_proposal([op2])
    res = preflight_proposal(prop, vault_root=tmp_path)
    assert res.operations[0].state == "invalid"
    assert res.operations[0].findings[0].code == "marker_injection"

    # 3. Candidate size limit
    # The original file is 81 bytes long.
    # We will read it with max_inspection_bytes=100.
    # "human\n<!-- lifeos:managed:start foo -->\n" = 40
    # + new_content + "\n"
    # + "<!-- lifeos:managed:end foo -->\nhuman" = 37
    # Total = 77 + len(new_content)
    # 15 bytes -> 92 bytes < 100 bytes limit
    op3 = ReplaceManagedBlock(
        id="op-3",
        target_path="block.md",
        block_name="foo",
        base_hash=original_hash,
        new_content="1"*15
    )
    prop = _make_dummy_proposal([op3])
    res = preflight_proposal(prop, vault_root=tmp_path, max_inspection_bytes=100)
    assert res.operations[0].state == "valid"

    # 25 bytes -> 102 bytes > 100 bytes limit
    op4 = ReplaceManagedBlock(
        id="op-4",
        target_path="block.md",
        block_name="foo",
        base_hash=original_hash,
        new_content="1"*25
    )
    prop = _make_dummy_proposal([op4])
    res = preflight_proposal(prop, vault_root=tmp_path, max_inspection_bytes=100)
    assert res.operations[0].state == "invalid"
    assert res.operations[0].findings[0].code == "candidate_too_large_for_inspection"


def test_symlink_parent_safety(tmp_path: Path) -> None:
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')

    # Create symlinked parent
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    sym_dir = tmp_path / "sym"
    sym_dir.symlink_to("real")

    op1 = CreateFile(id="op-1", target_path="sym/a.txt", expected_target_state="absent", new_content="content")
    prop = _make_dummy_proposal([op1])
    res = preflight_proposal(prop, vault_root=tmp_path)

    assert res.operations[0].state == "invalid"
    assert res.operations[0].findings[0].code == "unsafe_path" or res.operations[0].findings[0].code == "unsafe_parent"

    # Note: _secure_io.py open_directory_secure currently rejects symlink traversals anyway.
    # Our manual check inside _evaluate_operation checks parent chain symlinks.


def test_missing_parent(tmp_path: Path) -> None:
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')

    op1 = CreateFile(id="op-1", target_path="missing_dir/a.txt", expected_target_state="absent", new_content="content")
    prop = _make_dummy_proposal([op1])
    res = preflight_proposal(prop, vault_root=tmp_path)

    assert res.operations[0].state == "invalid"
    assert res.operations[0].findings[0].code == "missing_parent"


def test_standard_generated_wiki_role_parent_may_be_missing(tmp_path: Path) -> None:
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')
    (tmp_path / "wiki").mkdir()

    operation = CreateGeneratedFile(
        id="op-1",
        target_path="wiki/concepts/active-recall.md",
        expected_target_state="absent",
        generator_id="gen1",
        new_content="content",
    )
    result = preflight_proposal(
        _make_dummy_proposal([operation]),
        vault_root=tmp_path,
    )

    assert result.operations[0].state == "valid"
    assert not (tmp_path / "wiki" / "concepts").exists()


def test_agent_selected_generated_wiki_parent_may_be_missing(tmp_path: Path) -> None:
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')
    (tmp_path / "wiki").mkdir()

    operation = CreateGeneratedFile(
        id="op-1",
        target_path="wiki/topics/learning/active-recall.md",
        expected_target_state="absent",
        generator_id="gen1",
        new_content="content",
    )
    result = preflight_proposal(
        _make_dummy_proposal([operation]),
        vault_root=tmp_path,
    )

    assert result.operations[0].state == "valid"
    assert not (tmp_path / "wiki" / "topics").exists()


def test_invalid_max_bytes(tmp_path: Path) -> None:
    prop = _make_dummy_proposal([])
    res = preflight_proposal(prop, vault_root=tmp_path, max_inspection_bytes=-1)
    assert res.state == "invalid"
    assert res.findings[0].code == "invalid_inspection_limit"

    res = preflight_proposal(prop, vault_root=tmp_path, max_inspection_bytes=0)
    assert res.state == "invalid"

    # boolean rejected because we strictly check `type() is not int` in code (if properly implemented, wait type(True) is bool)
    # let's assert this
    res = preflight_proposal(prop, vault_root=tmp_path, max_inspection_bytes=True) # type: ignore
    assert res.state == "invalid"
    assert res.findings[0].code == "invalid_inspection_limit"


def test_agent_selected_generated_flashcard_parent_may_be_missing(tmp_path: Path) -> None:
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')
    (tmp_path / "flashcards").mkdir()

    operation = CreateGeneratedFile(
        id="op-1",
        target_path="flashcards/driving-licence/traffic/right-of-way.md",
        expected_target_state="absent",
        generator_id="gen1",
        new_content="content",
    )
    result = preflight_proposal(_make_dummy_proposal([operation]), vault_root=tmp_path)

    assert result.operations[0].state == "valid"
    assert not (tmp_path / "flashcards" / "driving-licence").exists()


def test_generated_flashcard_missing_canonical_root_is_invalid(tmp_path: Path) -> None:
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')

    operation = CreateGeneratedFile(
        id="op-1",
        target_path="flashcards/driving-licence/right-of-way.md",
        expected_target_state="absent",
        generator_id="gen1",
        new_content="content",
    )
    result = preflight_proposal(_make_dummy_proposal([operation]), vault_root=tmp_path)

    assert result.operations[0].state == "invalid"
    assert result.operations[0].findings[0].code == "missing_parent"
