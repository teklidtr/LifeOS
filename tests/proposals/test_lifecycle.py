import pytest
from lifeos.proposals import (
    ProposalStatus,
    ProposalMetadata,
    TransitionError,
    submit_metadata_for_review,
    approve_metadata,
    reject_metadata,
)
from lifeos.proposals.lifecycle import serialize_proposal_markdown, compute_review_digest
from lifeos.proposals.patches import PatchDocument


def _make_meta(**kwargs) -> ProposalMetadata:
    base = {
        "id": "prop-20260713T000000Z-a1b2c3d4",
        "schema_version": 1,
        "patch_schema_version": 1,
        "lifecycle_schema_version": None,
        "title": "T",
        "description": "D",
        "status": "draft",
        "risk": "low",
        "created_at": "2026-07-13T00:00:00Z",
        "created_by": "system",
        "submitted_at": None,
        "submitted_by": None,
        "review_digest": None,
        "approved_at": None,
        "approved_by": None,
        "rejected_at": None,
        "rejected_by": None,
        "rejection_reason": None,
        "applied_at": None,
        "applied_by": None,
        "related_goals": [],
        "related_sources": [],
        "extensions": {},
    }
    base.update(kwargs)
    from lifeos.proposals.schema import validate_metadata

    return validate_metadata(base)


def test_pure_transitions():
    meta = _make_meta()

    # legacy non-draft rejection
    meta_legacy_pending = _make_meta(
        status="pending", submitted_by="u", submitted_at="2026-07-13T01:00:00Z", review_digest="d"
    )
    with pytest.raises(TransitionError, match="Legacy non-draft"):
        submit_metadata_for_review(
            meta_legacy_pending,
            submitted_by="u",
            submitted_at="2026-07-13T01:00:00Z",
            review_digest="d",
        )

    # submit
    submitted = submit_metadata_for_review(
        meta, submitted_by="u1", submitted_at="2026-07-13T01:00:00Z", review_digest="sha256:abc"
    )
    assert submitted.status == ProposalStatus.PENDING
    assert submitted.lifecycle_schema_version == 1
    assert submitted.review_digest == "sha256:abc"

    # approve
    approved = approve_metadata(
        submitted,
        approved_by="u2",
        approved_at="2026-07-13T02:00:00Z",
        current_review_digest="sha256:abc",
    )
    assert approved.status == ProposalStatus.APPROVED
    assert approved.approved_by == "u2"

    # reject (from pending)
    rejected = reject_metadata(
        submitted,
        rejected_by="u3",
        rejected_at="2026-07-13T03:00:00Z",
        rejection_reason="No.",
        current_review_digest="sha256:abc",
    )
    assert rejected.status == ProposalStatus.REJECTED

    # mismatch digest
    with pytest.raises(TransitionError, match="digest"):
        approve_metadata(
            submitted,
            approved_by="u",
            approved_at="2026-07-13T02:00:00Z",
            current_review_digest="sha256:bad",
        )


def test_compute_review_digest():
    meta = _make_meta()
    doc = PatchDocument(1, "prop-20260713T000000Z-a1b2c3d4", ())
    d = compute_review_digest(meta, "body", doc)
    assert d.startswith("sha256:")


def test_compute_review_digest_supports_nested_extensions():
    meta = _make_meta(extensions={"nested": {"values": [1, 2, 3]}})
    doc = PatchDocument(1, "prop-20260713T000000Z-a1b2c3d4", ())

    digest = compute_review_digest(meta, "body", doc)

    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_serialize_proposal_markdown():
    meta = _make_meta()
    b = serialize_proposal_markdown(meta, "hello\nworld")
    assert b.startswith(b"---\n")
    assert b.endswith(b"---\nhello\nworld")
    assert b"id: prop-20260713T000000Z-a1b2c3d4\n" in b
    assert b"title: T\n" in b


def test_filesystem_snapshot(tmp_path):
    # Setup dummy directory
    prop_dir = tmp_path / "prop-20260713T000000Z-a1b2c3d4"
    prop_dir.mkdir()
    md_file = prop_dir / "proposal.md"
    patch_file = prop_dir / "patches.json"
    other_file = prop_dir / "other.txt"

    # Write initial files
    meta = _make_meta()
    md_content = serialize_proposal_markdown(meta, "body")
    md_file.write_bytes(md_content)

    from lifeos.proposals.patches import serialize_patch_json_bytes, PatchDocument

    patch_doc = PatchDocument(1, "prop-20260713T000000Z-a1b2c3d4", ())
    patch_content = serialize_patch_json_bytes(patch_doc)
    patch_file.write_bytes(patch_content)

    other_file.write_text("should not change")

    from lifeos.proposals.loader import load_proposal_directory

    loaded = load_proposal_directory(prop_dir, proposals_root=tmp_path)
    assert loaded.proposal is not None

    from lifeos.proposals.lifecycle import submit_proposal_for_review

    res = submit_proposal_for_review(
        loaded.proposal,
        submitted_by="u",
        submitted_at="2026-07-13T01:00:00Z",
        proposals_root=tmp_path,
    )

    assert res.write_occurred

    # Assert patches and other files are unchanged
    assert patch_file.read_bytes() == patch_content
    assert other_file.read_text() == "should not change"

    # Assert proposal.md did change
    assert md_file.read_bytes() != md_content

    # Assert no locks or temporary files remain
    files = list(prop_dir.iterdir())
    names = {f.name for f in files}
    assert names == {"proposal.md", "patches.json", "other.txt"}


def _setup_dir(tmp_path):
    prop_dir = tmp_path / "prop-20260713T000000Z-a1b2c3d4"
    if not prop_dir.exists():
        prop_dir.mkdir()
    md_file = prop_dir / "proposal.md"
    patch_file = prop_dir / "patches.json"

    meta = _make_meta()
    md_content = serialize_proposal_markdown(meta, "body")
    md_file.write_bytes(md_content)

    from lifeos.proposals.patches import serialize_patch_json_bytes, PatchDocument

    patch_doc = PatchDocument(1, "prop-20260713T000000Z-a1b2c3d4", ())
    patch_content = serialize_patch_json_bytes(patch_doc)
    patch_file.write_bytes(patch_content)
    return prop_dir, md_file, patch_file


def test_lock_cleanup_failure_identity(tmp_path, monkeypatch):
    import os

    prop_dir, md_file, patch_file = _setup_dir(tmp_path)
    from lifeos.proposals.loader import load_proposal_directory
    from lifeos.proposals.lifecycle import submit_proposal_for_review

    loaded = load_proposal_directory(prop_dir, proposals_root=tmp_path).proposal

    orig_fstat = os.fstat

    def mocked_fstat(fd):
        st = orig_fstat(fd)

        class FakeStat:
            def __getattr__(self, name):
                if name == "st_ino":
                    return st.st_ino + 1
                return getattr(st, name)

        return FakeStat()

    monkeypatch.setattr(os, "fstat", mocked_fstat)

    res = submit_proposal_for_review(
        loaded, submitted_by="u", submitted_at="2026-07-13T01:00:00Z", proposals_root=tmp_path
    )

    assert res.write_occurred is True
    assert res.lock_released is False
    assert (prop_dir / ".lifeos-transition.lock").exists()


def test_lock_cleanup_failure_token(tmp_path, monkeypatch):
    import os

    prop_dir, md_file, patch_file = _setup_dir(tmp_path)
    from lifeos.proposals.loader import load_proposal_directory
    from lifeos.proposals.lifecycle import submit_proposal_for_review

    loaded = load_proposal_directory(prop_dir, proposals_root=tmp_path).proposal

    orig_read = os.read

    def mocked_read(fd, n):
        if n == 1024:
            return b"wrong_token"
        return orig_read(fd, n)

    monkeypatch.setattr(os, "read", mocked_read)

    res = submit_proposal_for_review(
        loaded, submitted_by="u", submitted_at="2026-07-13T01:00:00Z", proposals_root=tmp_path
    )

    assert res.write_occurred is True
    assert res.lock_released is False
    assert (prop_dir / ".lifeos-transition.lock").exists()


def test_source_revalidation_md_mutated(tmp_path):
    prop_dir, md_file, _ = _setup_dir(tmp_path)
    from lifeos.proposals.loader import load_proposal_directory
    from lifeos.proposals.lifecycle import submit_proposal_for_review

    loaded = load_proposal_directory(prop_dir, proposals_root=tmp_path).proposal

    import lifeos.proposals.lifecycle

    orig_atomic = lifeos.proposals.lifecycle.atomic_write_file_secure

    def mocked_atomic(dir_fd, filename, content, *, pre_replace_check=None):
        if filename == "proposal.md":
            md_file.write_bytes(md_file.read_bytes() + b" mutation")
            if pre_replace_check:
                pre_replace_check()
        return orig_atomic(dir_fd, filename, content, pre_replace_check=pre_replace_check)

    lifeos.proposals.lifecycle.atomic_write_file_secure = mocked_atomic
    try:
        with pytest.raises(TransitionError) as exc:
            submit_proposal_for_review(
                loaded,
                submitted_by="u",
                submitted_at="2026-07-13T01:00:00Z",
                proposals_root=tmp_path,
            )
        assert exc.value.code == "stale_proposal_source"
        assert exc.value.write_occurred is False
    finally:
        lifeos.proposals.lifecycle.atomic_write_file_secure = orig_atomic


def test_source_revalidation_json_mutated(tmp_path):
    prop_dir, _, patch_file = _setup_dir(tmp_path)
    from lifeos.proposals.loader import load_proposal_directory
    from lifeos.proposals.lifecycle import submit_proposal_for_review

    loaded = load_proposal_directory(prop_dir, proposals_root=tmp_path).proposal

    import lifeos.proposals.lifecycle

    orig_atomic = lifeos.proposals.lifecycle.atomic_write_file_secure

    def mocked_atomic(dir_fd, filename, content, *, pre_replace_check=None):
        if filename == "proposal.md":
            patch_file.write_bytes(patch_file.read_bytes() + b" mutation")
            if pre_replace_check:
                pre_replace_check()
        return orig_atomic(dir_fd, filename, content, pre_replace_check=pre_replace_check)

    lifeos.proposals.lifecycle.atomic_write_file_secure = mocked_atomic
    try:
        with pytest.raises(TransitionError) as exc:
            submit_proposal_for_review(
                loaded,
                submitted_by="u",
                submitted_at="2026-07-13T01:00:00Z",
                proposals_root=tmp_path,
            )
        assert exc.value.code == "changed_patch_source"
        assert exc.value.write_occurred is False
    finally:
        lifeos.proposals.lifecycle.atomic_write_file_secure = orig_atomic


def test_compute_review_digest_no_trailing_newline(monkeypatch):
    import json

    meta = _make_meta()
    from lifeos.proposals.lifecycle import compute_review_digest
    from lifeos.proposals.patches import PatchDocument

    captured = []
    orig_dumps = json.dumps

    def mock_dumps(*args, **kwargs):
        res = orig_dumps(*args, **kwargs)
        captured.append(res)
        return res

    monkeypatch.setattr(json, "dumps", mock_dumps)

    compute_review_digest(meta, "body text", PatchDocument(1, "prop-20260713T000000Z-a1b2c3d4", ()))
    assert len(captured) == 1
    encoded = captured[0].encode("utf-8")
    assert not encoded.endswith(b"\n")


def test_serialization_byte_level():
    meta = _make_meta()
    body = "body\nwith\ncr\r\nand lf\n"
    from lifeos.proposals.lifecycle import serialize_proposal_markdown

    b = serialize_proposal_markdown(meta, body)
    assert b.endswith(b"body\nwith\ncr\r\nand lf\n")


def test_v2_review_digest_mutates_on_generator_version():
    from lifeos.proposals.patches import (
        PatchDocumentV2,
        CreateGeneratedFileV2,
        ReplaceGeneratedFileV2,
    )

    meta = _make_meta()

    # Base Create operation
    op_create_1 = CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "gen-1", "v1.0.0", "data")
    doc_1 = PatchDocumentV2(2, "prop-20260713T000000Z-a1b2c3d4", (op_create_1,))
    digest_1 = compute_review_digest(meta, "body", doc_1)

    # Change only CreateGeneratedFileV2.generator_version
    op_create_2 = CreateGeneratedFileV2("op-1", "gen1.txt", "absent", "gen-1", "v2.0.0", "data")
    doc_2 = PatchDocumentV2(2, "prop-20260713T000000Z-a1b2c3d4", (op_create_2,))
    digest_2 = compute_review_digest(meta, "body", doc_2)
    assert digest_1 != digest_2

    # Base Replace operation
    op_replace_1 = ReplaceGeneratedFileV2(
        "op-2", "gen2.txt", "sha256:" + "0" * 64, "gen-2", "v1.0.0", "data"
    )
    doc_3 = PatchDocumentV2(2, "prop-20260713T000000Z-a1b2c3d4", (op_replace_1,))
    digest_3 = compute_review_digest(meta, "body", doc_3)

    # Change only ReplaceGeneratedFileV2.generator_version
    op_replace_2 = ReplaceGeneratedFileV2(
        "op-2", "gen2.txt", "sha256:" + "0" * 64, "gen-2", "v2.0.0", "data"
    )
    doc_4 = PatchDocumentV2(2, "prop-20260713T000000Z-a1b2c3d4", (op_replace_2,))
    digest_4 = compute_review_digest(meta, "body", doc_4)
    assert digest_3 != digest_4


def test_v1_golden_review_digest():
    meta = _make_meta()
    from lifeos.proposals.patches import (
        ReplaceManagedBlock,
        CreateGeneratedFile,
        ReplaceGeneratedFile,
        CreateFile,
        PatchHumanFile,
    )

    doc = PatchDocument(
        schema_version=1,
        proposal_id="prop-20260713T000000Z-a1b2c3d4",
        operations=(
            ReplaceManagedBlock("op-1", "target.md", "sha256:" + "0" * 64, "block-1", "content 1"),
            CreateGeneratedFile("op-2", "gen1.txt", "absent", "generator-1", "content 2"),
            ReplaceGeneratedFile(
                "op-3", "gen2.txt", "sha256:" + "0" * 64, "generator-2", "content 3"
            ),
            CreateFile("op-4", "file.txt", "absent", "content 4"),
            PatchHumanFile("op-5", "human.txt", "sha256:" + "0" * 64, "diff 5"),
        ),
    )
    d = compute_review_digest(meta, "body", doc)
    assert d == "sha256:a96f934f195a6db3b54f137501b4bc5d52a3ab60115d5d7d3c392df3544da66b"


def test_v1_transition_does_not_migrate_to_v2(tmp_path):
    import json

    prop_dir, md_file, patch_file = _setup_dir(tmp_path)
    from lifeos.proposals.loader import load_proposal_directory
    from lifeos.proposals.lifecycle import submit_proposal_for_review

    loaded = load_proposal_directory(prop_dir, proposals_root=tmp_path).proposal

    res = submit_proposal_for_review(
        loaded, submitted_by="u", submitted_at="2026-07-13T01:00:00Z", proposals_root=tmp_path
    )
    assert res.write_occurred is True

    patches_json = json.loads(patch_file.read_bytes())
    assert patches_json["schema_version"] == 1
    assert loaded.patch_document.schema_version == 1
