import pytest
import os
import json

import hashlib
import lifeos.proposals.application as application_module
from lifeos.proposals.application import apply_proposal, ApplicationError, OperationState, ApplicationErrorCode
from lifeos.proposals.recovery import (
    RecoveryPhase,
    discover_recovery_state,
    unresolved_recovery_journals,
)
from lifeos.proposals.loader import load_proposal_directory
from lifeos.proposals.patches import (
    PatchDocumentV2,
    CreateGeneratedFileV2,
    ReplaceGeneratedFileV2,
    PatchDocument,
    CreateGeneratedFile,
    serialize_patch_json_bytes,
    ReplaceManagedBlock,
)
from lifeos.proposals.schema import validate_metadata, ProposalStatus
from lifeos.proposals.lifecycle import serialize_proposal_markdown


def _make_meta(**kwargs):
    base = {
        "id": "prop-20260713T000000Z-a1b2c3d4",
        "schema_version": 1,
        "patch_schema_version": 2,
        "lifecycle_schema_version": 1,
        "title": "T",
        "description": "D",
        "status": "approved",
        "risk": "low",
        "created_at": "2026-07-13T00:00:00Z",
        "created_by": "system",
        "submitted_at": "2026-07-13T01:00:00Z",
        "submitted_by": "u",
        "review_digest": f"sha256:{hashlib.sha256(b'abc').hexdigest()}",
        "approved_at": "2026-07-13T02:00:00Z",
        "approved_by": "admin",
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
    return validate_metadata(base)


def _setup_proposal(tmp_path, meta, patch_doc, ownership_data=None):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    proposals_root = vault_root / "proposals"
    proposals_root.mkdir()
    prop_dir = proposals_root / meta.id
    prop_dir.mkdir()

    md_content = serialize_proposal_markdown(meta, "body")
    (prop_dir / "proposal.md").write_bytes(md_content)

    patch_content = serialize_patch_json_bytes(patch_doc)
    (prop_dir / "patches.json").write_bytes(patch_content)

    sys_dir = vault_root / "system"
    sys_dir.mkdir(parents=True, exist_ok=True)
    man_path = sys_dir / "generated-ownership.json"
    if ownership_data is None:
        ownership_data = {"schema_version": 1, "owned_files": {}}
        for op in patch_doc.operations:
            if hasattr(op, "op") and op.op == "replace_generated_file":
                path = getattr(op, "file_path", getattr(op, "target_path", "test.txt"))
                exp_hash = getattr(op, "base_hash", getattr(op, "expected_hash", None))
                if exp_hash.startswith("sha256:"):
                    exp_hash = exp_hash[7:]
                ownership_data["owned_files"][path] = {
                    "generator_id": getattr(
                        op, "expected_generator_id", getattr(op, "generator_id", "gen-1")
                    ),
                    "generator_version": getattr(op, "generator_version", "v1"),
                    "content_hash": exp_hash,
                    "created_at": "2026-07-13T00:00:00Z",
                    "updated_at": "2026-07-13T00:00:00Z",
                }
    man_path.write_text(json.dumps(ownership_data))

    return vault_root, proposals_root, prop_dir


# 1. Staging in the final target parent, Random exclusive staging names, Initial mode 0o600, Partial write handling
def test_staging_artifacts_created_correctly(tmp_path, monkeypatch):
    meta = _make_meta()
    op = CreateGeneratedFileV2("op-1", "test.txt", "absent", "gen-1", "v1", "hello")
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    staging_files = []
    orig_open = os.open

    def mock_open(path, flags, mode=0o777, dir_fd=None):
        if ".test.txt." in str(path) and ".staged" in str(path):
            if flags & os.O_CREAT:
                assert flags & os.O_EXCL
                assert flags & os.O_WRONLY
                assert mode == 0o600
                staging_files.append(path)
        return orig_open(path, flags, mode, dir_fd=dir_fd)

    os.supports_dir_fd.add(mock_open)
    monkeypatch.setattr(os, "open", mock_open)

    res = apply_proposal(
        loaded.proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )
    assert res.new_status == ProposalStatus.APPLIED
    assert len(staging_files) == 1

    # Target should now exist
    assert (vault_root / "test.txt").read_text() == "hello"


# 2. Missing parent rejection, no automatic parent creation
def test_missing_parent_rejection(tmp_path):
    meta = _make_meta()
    op = CreateGeneratedFileV2("op-1", "missing/test.txt", "absent", "gen-1", "v1", "hello")
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    with pytest.raises(ApplicationError) as exc_info:
        apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )
    assert "Missing parent directory" in str(exc_info.value.__cause__)
    assert exc_info.value.code == ApplicationErrorCode.PREFLIGHT_FAILED
    assert exc_info.value.code == ApplicationErrorCode.PREFLIGHT_FAILED
    assert exc_info.value.code == ApplicationErrorCode.PREFLIGHT_FAILED
    assert not (vault_root / "missing").exists()


def test_agent_selected_nested_wiki_parent_is_created_lazily(tmp_path):
    meta = _make_meta()
    op = CreateGeneratedFileV2(
        "op-1",
        "wiki/learning/memory/active-recall.md",
        "absent",
        "gen-1",
        "v1",
        "hello",
    )
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    (vault_root / "wiki").mkdir()
    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None
    assert not (vault_root / "wiki" / "learning").exists()

    result = apply_proposal(
        loaded.proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )

    assert result.new_status == ProposalStatus.APPLIED
    assert (vault_root / "wiki" / "learning" / "memory" / "active-recall.md").read_text() == "hello"


# 3. Same-directory hardlink backups, backup identity and hash
def test_hardlink_backups(tmp_path, monkeypatch):
    meta = _make_meta()
    old_hash = f"sha256:{hashlib.sha256(b'old_content').hexdigest()}"
    op = ReplaceGeneratedFileV2("op-1", "test.txt", old_hash, "gen-1", "v1", "new_content")
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    (vault_root / "test.txt").write_text("old_content")

    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    linked_files = []
    orig_link = os.link

    def mock_link(src, dst, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=True):
        if ".backup" in str(dst):
            linked_files.append((src, dst))
        orig_link(
            src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks
        )

    monkeypatch.setattr(os, "link", mock_link)

    apply_proposal(
        loaded.proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )

    # Verify backup linked
    assert any("test.txt" in str(s) for s, d in linked_files)
    assert (vault_root / "test.txt").read_text() == "new_content"


# 4. Preparation abort when hardlinks are unavailable
def test_hardlink_unavailable_aborts(tmp_path, monkeypatch):
    meta = _make_meta()
    old_hash = f"sha256:{hashlib.sha256(b'old_content').hexdigest()}"
    op = ReplaceGeneratedFileV2("op-1", "test.txt", old_hash, "gen-1", "v1", "new_content")
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    (vault_root / "test.txt").write_text("old_content")

    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    orig_link = os.link

    def mock_link(src, dst, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=True):
        if ".backup" in str(dst):
            raise OSError("Links not supported on this filesystem")
        orig_link(
            src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks
        )

    monkeypatch.setattr(os, "link", mock_link)

    with pytest.raises(ApplicationError) as exc_info:
        apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )
    assert "Links not supported on this filesystem" in str(
        exc_info.value.__cause__
    ) or "Backup content hash mismatch" in str(exc_info.value.__cause__)


# 5. Staging clobber prevention (O_EXCL check)
def test_raced_in_creation_fails(tmp_path, monkeypatch):
    meta = _make_meta()
    op = CreateGeneratedFileV2("op-1", "test.txt", "absent", "gen-1", "v1", "hello")
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    orig_link = os.link

    def mock_link(src, dst, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=True):
        if "test.txt" == str(dst) and ".staged" not in str(src):
            pass  # we only intercept the final publish link
        if dst == "test.txt" or str(dst) == "test.txt":
            # Simulate a race
            (vault_root / "test.txt").write_text("raced_content")
        orig_link(
            src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks
        )

    monkeypatch.setattr(os, "link", mock_link)

    with pytest.raises(ApplicationError) as exc_info:
        apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )
    assert "File exists" in str(exc_info.value.__cause__)
    assert exc_info.value.code == ApplicationErrorCode.COMMIT_FAILED
    assert exc_info.value.code == ApplicationErrorCode.COMMIT_FAILED
    assert exc_info.value.code == ApplicationErrorCode.COMMIT_FAILED
    assert (vault_root / "test.txt").read_text() == "raced_content"


# 6. Revalidation rejection on external mutation
def test_replacement_revalidation_fails_on_mutation(tmp_path, monkeypatch):
    meta = _make_meta()
    old_hash = f"sha256:{hashlib.sha256(b'old_content').hexdigest()}"
    op = ReplaceGeneratedFileV2("op-1", "test.txt", old_hash, "gen-1", "v1", "new_content")
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    (vault_root / "test.txt").write_text("old_content")

    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    orig_replace = os.replace

    def mock_replace(src, dst, src_dir_fd=None, dst_dir_fd=None):
        if dst == "test.txt" or str(dst) == "test.txt":
            # We are inside the publish_replacement call but before it succeeds...
            # Wait, the verification happens *before* os.replace. So we need to mutate it earlier.
            pass
        orig_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    # We can mutate it during backup creation
    orig_link = os.link

    def mock_link(src, dst, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=True):
        orig_link(
            src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks
        )
        if ".backup" in str(dst):
            (vault_root / "test.txt").write_text("mutated")

    monkeypatch.setattr(os, "link", mock_link)

    with pytest.raises(ApplicationError) as exc_info:
        apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )
    assert "Links not supported on this filesystem" in str(
        exc_info.value.__cause__
    ) or "Backup content hash mismatch" in str(exc_info.value.__cause__)


# 7. V1 generated-operation rejection
def test_v1_generated_operation_rejection(tmp_path):
    meta = _make_meta(patch_schema_version=1)
    op = CreateGeneratedFile("op-1", "test.txt", "absent", "gen-1", "hello")
    doc = PatchDocument(1, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    with pytest.raises(ApplicationError, match="unsupported_generated_provenance"):
        apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )


# 8. Managed-block body receives no implicit newline
def test_managed_block_exact_boundaries(tmp_path):
    meta = _make_meta()

    # Original content has no newline at EOF
    orig_content = "some text\n<!-- lifeos:managed:start myblock -->\ninner\n<!-- lifeos:managed:end myblock -->\nmore text"

    op = ReplaceManagedBlock(
        "op-1",
        "human.md",
        f"sha256:{hashlib.sha256(orig_content.encode('utf-8')).hexdigest()}",
        "myblock",
        "new_inner\n",
    )
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)

    # Original content has no newline at EOF
    orig_content = "some text\n<!-- lifeos:managed:start myblock -->\ninner\n<!-- lifeos:managed:end myblock -->\nmore text"
    (vault_root / "human.md").write_text(orig_content)

    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    apply_proposal(
        loaded.proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )

    final_content = (vault_root / "human.md").read_text()
    expected = "some text\n<!-- lifeos:managed:start myblock -->\nnew_inner\n<!-- lifeos:managed:end myblock -->\nmore text"
    assert final_content == expected


# 9. Rollback refusal after external modification
def test_rollback_refusal_on_external_mutation(tmp_path, monkeypatch):
    meta = _make_meta()
    op1 = CreateGeneratedFileV2("op-1", "test1.txt", "absent", "gen-1", "v1", "hello")
    op2 = CreateGeneratedFileV2("op-2", "test2.txt", "absent", "gen-1", "v1", "world")
    doc = PatchDocumentV2(2, meta.id, (op1, op2))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    orig_link = os.link

    def mock_link(src, dst, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=True):
        if dst == "test2.txt" or str(dst) == "test2.txt":
            (vault_root / "test1.txt").write_text("mutated externally")
            raise OSError("Fail on op2 link to trigger rollback")
        orig_link(
            src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks
        )

    monkeypatch.setattr(os, "link", mock_link)

    with pytest.raises(ApplicationError) as exc_info:
        apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    outcome = exc_info.value.outcome
    print("EXCEPTION:", exc_info.value)
    print("FINAL OUTCOME:", outcome)
    assert outcome.rollback_succeeded is False
    assert outcome.recovery_required is True
    assert outcome.operation_results[0].state == OperationState.ROLLBACK_FAILED


def test_preparation_invariants(tmp_path, monkeypatch):
    import hashlib

    meta = _make_meta()
    old_hash = f"sha256:{hashlib.sha256(b'old_content').hexdigest()}"
    op1 = ReplaceGeneratedFileV2("op-1", "test1.txt", old_hash, "gen-1", "v1", "new_content1")
    op2 = CreateGeneratedFileV2("op-2", "test2.txt", "absent", "gen-1", "v1", "new_content2")
    doc = PatchDocumentV2(2, meta.id, (op1, op2))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    (vault_root / "test1.txt").write_bytes(b"old_content")
    (vault_root / "test1.txt").chmod(0o644)

    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    # Snapshot exact canonical bytes before application
    original_target_bytes = (vault_root / "test1.txt").read_bytes()
    original_ownership_bytes = (vault_root / "system/generated-ownership.json").read_bytes()
    original_proposal_bytes = (vault_root / "proposals" / meta.id / "proposal.md").read_bytes()
    original_patches_bytes = (vault_root / "proposals" / meta.id / "patches.json").read_bytes()

    invariants_checked = False
    fsynced_inodes = set()

    orig_fsync = os.fsync

    def mock_fsync(fd):
        try:
            st = os.fstat(fd)
            fsynced_inodes.add((st.st_dev, st.st_ino))
        except OSError:
            pass
        orig_fsync(fd)

    monkeypatch.setattr(os, "fsync", mock_fsync)

    orig_replace = os.replace

    def mock_replace(src, dst, src_dir_fd=None, dst_dir_fd=None):
        nonlocal invariants_checked
        # This is called during the first canonical commit
        if str(dst) == "test1.txt" and not invariants_checked:
            try:
                staged_files = [p for p in vault_root.iterdir() if p.name.endswith(".staged")]
                backup_files = [p for p in vault_root.iterdir() if p.name.endswith(".backup")]
                sys_staged = [
                    p for p in (vault_root / "system").iterdir() if p.name.endswith(".staged")
                ]
                sys_backup = [
                    p for p in (vault_root / "system").iterdir() if p.name.endswith(".backup")
                ]
                prop_staged = [
                    p
                    for p in (vault_root / "proposals" / meta.id).iterdir()
                    if p.name.endswith(".staged")
                ]
                prop_backup = [
                    p
                    for p in (vault_root / "proposals" / meta.id).iterdir()
                    if p.name.endswith(".backup")
                ]

                # Check exact staging set
                assert len(staged_files) == 2
                assert any(p.name.startswith(".test1.txt.") for p in staged_files)
                assert any(p.name.startswith(".test2.txt.") for p in staged_files)

                assert len(sys_staged) == 1
                assert any(p.name.startswith(".generated-ownership.json.") for p in sys_staged)

                assert len(prop_staged) == 1
                assert any(p.name.startswith(".proposal.md.") for p in prop_staged)

                # Check exact backup set
                assert len(backup_files) == 1
                assert any(p.name.startswith(".test1.txt.") for p in backup_files)

                assert len(sys_backup) == 1
                assert any(p.name.startswith(".generated-ownership.json.") for p in sys_backup)

                assert len(prop_backup) == 1
                assert any(p.name.startswith(".proposal.md.") for p in prop_backup)

                test1_stg = next(p for p in staged_files if p.name.startswith(".test1.txt."))
                test2_stg = next(p for p in staged_files if p.name.startswith(".test2.txt."))
                sys_stg = next(
                    p for p in sys_staged if p.name.startswith(".generated-ownership.json.")
                )
                prop_stg = next(p for p in prop_staged if p.name.startswith(".proposal.md."))

                test1_bkp = next(p for p in backup_files if p.name.startswith(".test1.txt."))
                sys_bkp = next(
                    p for p in sys_backup if p.name.startswith(".generated-ownership.json.")
                )
                prop_bkp = next(p for p in prop_backup if p.name.startswith(".proposal.md."))

                # Assert backups are in the same directory as canonical
                assert test1_bkp.parent == vault_root
                assert sys_bkp.parent == (vault_root / "system")
                assert prop_bkp.parent == (vault_root / "proposals" / meta.id)

                # device equals original device, inode equals original inode
                orig_t1_st = os.stat(vault_root / "test1.txt")
                assert test1_bkp.stat().st_dev == orig_t1_st.st_dev
                assert test1_bkp.stat().st_ino == orig_t1_st.st_ino
                assert (
                    hashlib.sha256(test1_bkp.read_bytes()).hexdigest()
                    == hashlib.sha256(original_target_bytes).hexdigest()
                )

                orig_sys_st = os.stat(vault_root / "system" / "generated-ownership.json")
                assert sys_bkp.stat().st_dev == orig_sys_st.st_dev
                assert sys_bkp.stat().st_ino == orig_sys_st.st_ino
                assert (
                    hashlib.sha256(sys_bkp.read_bytes()).hexdigest()
                    == hashlib.sha256(original_ownership_bytes).hexdigest()
                )

                orig_prop_st = os.stat(vault_root / "proposals" / meta.id / "proposal.md")
                assert prop_bkp.stat().st_dev == orig_prop_st.st_dev
                assert prop_bkp.stat().st_ino == orig_prop_st.st_ino
                assert (
                    hashlib.sha256(prop_bkp.read_bytes()).hexdigest()
                    == hashlib.sha256(original_proposal_bytes).hexdigest()
                )

                # For every staging file, assert exact candidate bytes, size, hash, fsync, correct mode
                assert test1_stg.read_bytes() == b"new_content1"
                assert test1_stg.stat().st_size == len(b"new_content1")
                assert (
                    hashlib.sha256(test1_stg.read_bytes()).hexdigest()
                    == hashlib.sha256(b"new_content1").hexdigest()
                )
                assert (
                    test1_stg.stat().st_mode & 0o777 == 0o644
                )  # Replacement targets retain exact original mode

                assert test2_stg.read_bytes() == b"new_content2"
                assert test2_stg.stat().st_size == len(b"new_content2")
                assert (
                    hashlib.sha256(test2_stg.read_bytes()).hexdigest()
                    == hashlib.sha256(b"new_content2").hexdigest()
                )
                assert test2_stg.stat().st_mode & 0o777 == 0o600  # Created targets are 0o600

                for p in [test1_stg, test2_stg, sys_stg, prop_stg]:
                    st = os.stat(p)
                    assert (st.st_dev, st.st_ino) in fsynced_inodes

                # Directory descriptors fsynced
                vault_st = os.stat(vault_root)
                assert (vault_st.st_dev, vault_st.st_ino) in fsynced_inodes
                sys_dir_st = os.stat(vault_root / "system")
                assert (sys_dir_st.st_dev, sys_dir_st.st_ino) in fsynced_inodes
                prop_dir_st = os.stat(vault_root / "proposals" / meta.id)
                assert (prop_dir_st.st_dev, prop_dir_st.st_ino) in fsynced_inodes

                # Assert exact original canonical bytes
                assert (vault_root / "test1.txt").read_bytes() == original_target_bytes
                assert not (vault_root / "test2.txt").exists()
                assert (
                    vault_root / "system/generated-ownership.json"
                ).read_bytes() == original_ownership_bytes
                assert (
                    vault_root / "proposals" / meta.id / "proposal.md"
                ).read_bytes() == original_proposal_bytes
                assert (
                    vault_root / "proposals" / meta.id / "patches.json"
                ).read_bytes() == original_patches_bytes

                invariants_checked = True
            except Exception:
                import traceback

                traceback.print_exc()
                raise

        orig_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "replace", mock_replace)

    apply_proposal(
        loaded.proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )
    assert invariants_checked


def test_successful_rollback_state(tmp_path, monkeypatch):
    meta = _make_meta()
    old_hash = f"sha256:{hashlib.sha256(b'old_content').hexdigest()}"
    op1 = ReplaceGeneratedFileV2("op-1", "test1.txt", old_hash, "gen-1", "v1", "new_content1")
    op2 = CreateGeneratedFileV2("op-2", "test2.txt", "absent", "gen-1", "v1", "new_content2")
    doc = PatchDocumentV2(2, meta.id, (op1, op2))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    (vault_root / "test1.txt").write_text("old_content")

    orig_ownership = (vault_root / "system/generated-ownership.json").read_text()

    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    # We force a failure during commit of test2.txt
    orig_link = os.link

    def mock_link(src, dst, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=True):
        if str(dst) == "test2.txt":
            raise OSError("Injected failure to trigger rollback")
        orig_link(
            src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks
        )

    monkeypatch.setattr(os, "link", mock_link)

    with pytest.raises(ApplicationError) as exc_info:
        apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    outcome = exc_info.value.outcome
    assert outcome.rollback_performed is True
    assert outcome.rollback_succeeded is True
    assert outcome.recovery_required is False

    # Verify exact state
    assert (vault_root / "test1.txt").read_text() == "old_content"
    assert not (vault_root / "test2.txt").exists()
    assert (vault_root / "system/generated-ownership.json").read_text() == orig_ownership
    assert "status: applied" not in (vault_root / "proposals" / meta.id / "proposal.md").read_text()


def test_unsafe_rollback_state(tmp_path, monkeypatch):
    meta = _make_meta()
    old_hash = f"sha256:{hashlib.sha256(b'old_content').hexdigest()}"
    op1 = ReplaceGeneratedFileV2("op-1", "test1.txt", old_hash, "gen-1", "v1", "new_content1")
    op2 = CreateGeneratedFileV2("op-2", "test2.txt", "absent", "gen-1", "v1", "new_content2")
    doc = PatchDocumentV2(2, meta.id, (op1, op2))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    (vault_root / "test1.txt").write_text("old_content")

    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    # Force failure on test2, and mutate test1 so rollback of test1 fails
    orig_link = os.link

    def mock_link(src, dst, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=True):
        if str(dst) == "test2.txt":
            # Mutate test1 to block rollback
            (vault_root / "test1.txt").write_text("externally_mutated")
            raise OSError("Injected failure")
        orig_link(
            src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks
        )

    monkeypatch.setattr(os, "link", mock_link)

    with pytest.raises(ApplicationError) as exc_info:
        apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    outcome = exc_info.value.outcome
    assert outcome.rollback_performed is True
    assert outcome.rollback_succeeded is False
    assert outcome.recovery_required is True

    assert (vault_root / "test1.txt").read_text() == "externally_mutated"


def test_ownership_creation_fields(tmp_path):
    meta = _make_meta()
    op = CreateGeneratedFileV2("op-1", "test.txt", "absent", "gen-1", "v1", "new_content")
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    apply_proposal(
        loaded.proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )

    manifest_data = json.loads((vault_root / "system/generated-ownership.json").read_text())
    entry = manifest_data["owned_files"]["test.txt"]
    assert entry["generator_id"] == "gen-1"
    assert entry["generator_version"] == "v1"
    assert entry["created_at"] == "2026-07-13T03:00:00Z"
    assert entry["updated_at"] == "2026-07-13T03:00:00Z"
    assert entry["content_hash"] == hashlib.sha256(b"new_content").hexdigest()


def test_ownership_replacement_fields(tmp_path):
    meta = _make_meta()
    old_hash = f"sha256:{hashlib.sha256(b'old_content').hexdigest()}"
    op = ReplaceGeneratedFileV2("op-1", "test.txt", old_hash, "gen-1", "v2", "new_content")
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    (vault_root / "test.txt").write_text("old_content")

    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None
    apply_proposal(
        loaded.proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )

    manifest_data = json.loads((vault_root / "system/generated-ownership.json").read_text())
    entry = manifest_data["owned_files"]["test.txt"]
    assert entry["generator_id"] == "gen-1"
    assert entry["generator_version"] == "v2"
    assert entry["created_at"] == "2026-07-13T00:00:00Z"  # preserved
    assert entry["updated_at"] == "2026-07-13T03:00:00Z"  # updated
    assert entry["content_hash"] == hashlib.sha256(b"new_content").hexdigest()


def test_structured_errors_no_raw_paths(tmp_path, monkeypatch):
    meta = _make_meta()
    op = CreateGeneratedFileV2("op-1", "test.txt", "absent", "gen-1", "v1", "new_content")
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    def fail_staging(*_args, **_kwargs):
        raise OSError(f"Permission denied: {vault_root / 'test.txt'}")

    monkeypatch.setattr(application_module, "create_staging_file", fail_staging)

    with pytest.raises(ApplicationError) as exc:
        apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )
    assert "Permission denied" not in str(exc.value)
    assert str(vault_root) not in str(exc.value)


def test_missing_original_mode_fails(tmp_path):
    import hashlib

    meta = _make_meta()
    old_hash = f"sha256:{hashlib.sha256(b'old_content').hexdigest()}"
    # Replace generated file but the target doesn't exist (simulating missing mode state without target not found because preflight might pass if we bypass it, actually preflight will fail, but let's mock get_target_identity to return None for a replacement to simulate missing state)
    op = ReplaceGeneratedFileV2("op-1", "test1.txt", old_hash, "gen-1", "v1", "new_content1")
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    (vault_root / "test1.txt").write_bytes(b"old_content")
    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    # We will just patch get_target_identity to return None
    import lifeos.proposals.application as app

    orig_get = app.get_target_identity

    def mock_get(name, desc):
        return None

    app.get_target_identity = mock_get

    import pytest

    with pytest.raises(app.ApplicationError) as exc_info:
        app.apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    app.get_target_identity = orig_get

    assert "Missing original mode for replacement" in str(
        exc_info.value.__cause__
    ) or "Missing original identity for replacement" in str(exc_info.value.__cause__)


def test_mode_creation_and_preservation(tmp_path):
    import stat
    import hashlib

    meta = _make_meta()
    op_create = CreateGeneratedFileV2("op-c", "test_create.txt", "absent", "gen-1", "v1", "new")
    op_replace = ReplaceGeneratedFileV2(
        "op-r",
        "test_replace.txt",
        "sha256:" + hashlib.sha256(b"old").hexdigest(),
        "gen-1",
        "v1",
        "new_rep",
    )
    doc = PatchDocumentV2(2, meta.id, (op_create, op_replace))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)

    replace_target = vault_root / "test_replace.txt"
    replace_target.write_text("old")
    replace_target.chmod(0o640)

    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None
    apply_proposal(
        loaded.proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )

    st_create = os.stat(vault_root / "test_create.txt")
    assert stat.S_IMODE(st_create.st_mode) == 0o600

    st_replace = os.stat(vault_root / "test_replace.txt")
    assert stat.S_IMODE(st_replace.st_mode) == 0o640


def test_public_error_redaction(tmp_path, monkeypatch):
    import errno
    import hashlib

    meta = _make_meta()
    op1 = ReplaceGeneratedFileV2(
        "op-1", "test1.txt", "sha256:" + hashlib.sha256(b"old").hexdigest(), "gen-1", "v1", "new"
    )
    op2 = CreateGeneratedFileV2("op-2", "test2.txt", "absent", "gen-1", "v1", "new")
    doc = PatchDocumentV2(2, meta.id, (op1, op2))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    (vault_root / "test1.txt").write_text("old")

    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    orig_replace = os.replace

    def mock_replace(src, dst, src_dir_fd=None, dst_dir_fd=None):
        if ".backup" in str(src):
            raise OSError(
                errno.EACCES, "Permission denied", "/private/tmp/secret-vault/generated-file.md"
            )
        orig_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    orig_link = os.link

    def mock_link(src, dst, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=True):
        if dst == "test2.txt" or str(dst) == "test2.txt":
            raise OSError("Injected")
        orig_link(
            src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks
        )

    monkeypatch.setattr(os, "link", mock_link)
    monkeypatch.setattr(os, "replace", mock_replace)

    with pytest.raises(ApplicationError) as exc_info:
        apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    err_str = str(exc_info.value)
    assert "/private/tmp/secret-vault/generated-file.md" not in err_str
    assert "Permission denied" not in err_str
    assert "Proposal rollback could not safely restore all committed paths." in err_str

    assert exc_info.value.code == ApplicationErrorCode.COMMIT_FAILED

    assert "/private/tmp/secret-vault" not in exc_info.value.message
    assert "Permission denied" not in exc_info.value.message

    import dataclasses
    import json

    outcome_dict = dataclasses.asdict(exc_info.value.outcome)
    outcome_str = json.dumps(outcome_dict)
    assert "/private/tmp/secret-vault" not in outcome_str
    assert "Permission denied" not in outcome_str


def test_missing_replacement_identity_fails():
    import pytest
    from lifeos.proposals.application import require_replacement_identity

    kinds = [
        "replace_generated_file",
        "replace_managed_block",
        "patch_human_file",
        "generated-ownership.json",
        "proposal.md",
    ]

    for kind in kinds:
        with pytest.raises(
            ValueError, match=f"Missing original identity for replacement of {kind}"
        ):
            require_replacement_identity(None, target_kind=kind)


class _InjectedInterruption(BaseException):
    pass


def _load_two_target_application(tmp_path):
    meta = _make_meta()
    old_hash = f"sha256:{hashlib.sha256(b'old_content').hexdigest()}"
    operations = (
        ReplaceGeneratedFileV2(
            "op-1", "test1.txt", old_hash, "gen-1", "v1", "new_content1"
        ),
        CreateGeneratedFileV2(
            "op-2", "test2.txt", "absent", "gen-1", "v1", "new_content2"
        ),
    )
    doc = PatchDocumentV2(2, meta.id, operations)
    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    (vault_root / "test1.txt").write_bytes(b"old_content")
    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None
    return meta, vault_root, loaded.proposal


def _interrupt_at(monkeypatch, checkpoint_name):
    def checkpoint(name):
        if name == checkpoint_name:
            raise _InjectedInterruption(name)

    monkeypatch.setattr(application_module, "_application_checkpoint", checkpoint)


def _single_recovery_journal(vault_root):
    discovery = discover_recovery_state(recovery_root=vault_root / ".lifeos" / "recovery")
    assert discovery.findings == ()
    assert len(discovery.journals) == 1
    return discovery.journals[0]


def test_apply_writes_prepared_journal_before_mutation(tmp_path, monkeypatch):
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    original_ownership = (vault_root / "system/generated-ownership.json").read_bytes()
    original_proposal = (vault_root / "proposals" / meta.id / "proposal.md").read_bytes()
    _interrupt_at(monkeypatch, "after_prepared_journal")

    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    journal = _single_recovery_journal(vault_root)
    assert journal.phase is RecoveryPhase.PREPARED
    assert (vault_root / "test1.txt").read_bytes() == b"old_content"
    assert not (vault_root / "test2.txt").exists()
    assert (vault_root / "system/generated-ownership.json").read_bytes() == original_ownership
    assert (vault_root / "proposals" / meta.id / "proposal.md").read_bytes() == original_proposal


def test_apply_refuses_unrecoverable_transaction(tmp_path, monkeypatch):
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    _interrupt_at(monkeypatch, "after_prepared_journal")
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    proposal_path = vault_root / "proposals" / meta.id / "proposal.md"
    proposal_path.write_text(proposal_path.read_text() + "\nmanual change\n")

    monkeypatch.setattr(application_module, "_application_checkpoint", lambda _name: None)
    with pytest.raises(ApplicationError) as exc_info:
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    assert exc_info.value.code is ApplicationErrorCode.RECOVERY_REQUIRED
    discovery = discover_recovery_state(recovery_root=vault_root / ".lifeos" / "recovery")
    assert len(unresolved_recovery_journals(discovery)) == 1


def test_fault_after_first_target_never_leaves_mixed_state(tmp_path, monkeypatch):
    _, vault_root, proposal = _load_two_target_application(tmp_path)
    _interrupt_at(monkeypatch, "after_target_install:0")

    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    journal = _single_recovery_journal(vault_root)
    assert journal.phase is RecoveryPhase.PREPARED
    assert (vault_root / "test1.txt").read_bytes() == b"new_content1"
    assert not (vault_root / "test2.txt").exists()
    tx_dir = vault_root / ".lifeos" / "recovery" / str(journal.transaction_id)
    for operation in journal.operations:
        assert (tx_dir / operation.staged_path).is_file()
        if operation.backup_path is not None:
            assert (tx_dir / operation.backup_path).is_file()


def test_fault_after_all_targets_preserves_recoverable_state(tmp_path, monkeypatch):
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    original_ownership = (vault_root / "system/generated-ownership.json").read_bytes()
    _interrupt_at(monkeypatch, "after_all_targets")

    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    journal = _single_recovery_journal(vault_root)
    assert journal.phase is RecoveryPhase.TARGETS_INSTALLED
    assert (vault_root / "test1.txt").read_bytes() == b"new_content1"
    assert (vault_root / "test2.txt").read_bytes() == b"new_content2"
    assert (vault_root / "system/generated-ownership.json").read_bytes() == original_ownership
    assert "status: applied" not in (
        vault_root / "proposals" / meta.id / "proposal.md"
    ).read_text()


def test_fault_after_ownership_install_preserves_recoverable_state(tmp_path, monkeypatch):
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    _interrupt_at(monkeypatch, "after_ownership_install")

    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    journal = _single_recovery_journal(vault_root)
    assert journal.phase is RecoveryPhase.TARGETS_INSTALLED
    ownership = json.loads((vault_root / "system/generated-ownership.json").read_text())
    assert ownership["owned_files"]["test1.txt"]["content_hash"] == hashlib.sha256(
        b"new_content1"
    ).hexdigest()
    assert ownership["owned_files"]["test2.txt"]["content_hash"] == hashlib.sha256(
        b"new_content2"
    ).hexdigest()
    assert "status: applied" not in (
        vault_root / "proposals" / meta.id / "proposal.md"
    ).read_text()


def test_fault_before_proposal_commit_preserves_recoverable_state(tmp_path, monkeypatch):
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    _interrupt_at(monkeypatch, "before_proposal_commit")

    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    journal = _single_recovery_journal(vault_root)
    assert journal.phase is RecoveryPhase.OWNERSHIP_INSTALLED
    assert (vault_root / "test1.txt").read_bytes() == b"new_content1"
    assert (vault_root / "test2.txt").read_bytes() == b"new_content2"
    assert "status: applied" not in (
        vault_root / "proposals" / meta.id / "proposal.md"
    ).read_text()


def test_ordinary_exception_restores_original_state(tmp_path, monkeypatch):
    meta, vault_root, proposal = _load_two_target_application(tmp_path)
    original_ownership = (vault_root / "system/generated-ownership.json").read_bytes()
    original_proposal = (vault_root / "proposals" / meta.id / "proposal.md").read_bytes()

    def checkpoint(name):
        if name == "after_target_install:0":
            raise RuntimeError("ordinary checkpoint failure")

    monkeypatch.setattr(application_module, "_application_checkpoint", checkpoint)
    with pytest.raises(RuntimeError, match="ordinary checkpoint failure"):
        apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    assert (vault_root / "test1.txt").read_bytes() == b"old_content"
    assert not (vault_root / "test2.txt").exists()
    assert (vault_root / "system/generated-ownership.json").read_bytes() == original_ownership
    assert (vault_root / "proposals" / meta.id / "proposal.md").read_bytes() == original_proposal
    discovery = discover_recovery_state(recovery_root=vault_root / ".lifeos" / "recovery")
    assert discovery.journals == ()
    assert discovery.findings == ()


def test_multi_target_application_uses_one_transaction(tmp_path):
    _, vault_root, proposal = _load_two_target_application(tmp_path)

    result = apply_proposal(
        proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )

    assert result.new_status is ProposalStatus.APPLIED
    discovery = discover_recovery_state(recovery_root=vault_root / ".lifeos" / "recovery")
    assert discovery.findings == ()
    assert len(discovery.journals) == 1
    journal = discovery.journals[0]
    assert journal.phase is RecoveryPhase.COMPLETE
    assert [operation.operation_id for operation in journal.operations] == ["op-1", "op-2"]


def test_retained_complete_transaction_does_not_block_new_apply(tmp_path):
    _, vault_root, first_proposal = _load_two_target_application(tmp_path)
    apply_proposal(
        first_proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )

    second_meta = _make_meta(id="prop-20260713T000001Z-a1b2c3d4")
    second_operation = CreateGeneratedFileV2(
        "op-3", "test3.txt", "absent", "gen-1", "v1", "new_content3"
    )
    second_document = PatchDocumentV2(2, second_meta.id, (second_operation,))
    proposals_root = vault_root / "proposals"
    second_dir = proposals_root / second_meta.id
    second_dir.mkdir()
    (second_dir / "proposal.md").write_bytes(
        serialize_proposal_markdown(second_meta, "body")
    )
    (second_dir / "patches.json").write_bytes(
        serialize_patch_json_bytes(second_document)
    )
    loaded = load_proposal_directory(second_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    result = apply_proposal(
        loaded.proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:01:00Z",
    )

    assert result.new_status is ProposalStatus.APPLIED
    assert (vault_root / "test3.txt").read_bytes() == b"new_content3"
    discovery = discover_recovery_state(recovery_root=vault_root / ".lifeos" / "recovery")
    assert discovery.findings == ()
    assert len(discovery.journals) == 1
    assert discovery.journals[0].phase is RecoveryPhase.COMPLETE


def test_failed_generated_create_removes_new_empty_wiki_parents(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = _make_meta()
    operation = CreateGeneratedFileV2(
        "op-1",
        "wiki/learning/memory/retrieval.md",
        "absent",
        "gen-1",
        "v1",
        "hello",
    )
    document = PatchDocumentV2(2, meta.id, (operation,))
    vault_root, proposals_root, proposal_dir = _setup_proposal(
        tmp_path, meta, document
    )
    (vault_root / "wiki").mkdir()
    loaded = load_proposal_directory(proposal_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    def fail_preparation(**kwargs: object) -> object:
        raise ValueError("forced preparation failure")

    monkeypatch.setattr(
        "lifeos.proposals.application._candidate_for_operation", fail_preparation
    )

    with pytest.raises(ApplicationError):
        apply_proposal(
            loaded.proposal,
            vault_root=vault_root,
            applied_by="admin",
            applied_at="2026-07-13T03:00:00Z",
        )

    assert not (vault_root / "wiki" / "learning").exists()


def test_agent_selected_nested_flashcard_parent_is_created_lazily(tmp_path):
    meta = _make_meta()
    op = CreateGeneratedFileV2(
        "op-1",
        "flashcards/driving-licence/traffic/right-of-way.md",
        "absent",
        "gen-1",
        "v1",
        "hello",
    )
    doc = PatchDocumentV2(2, meta.id, (op,))

    vault_root, proposals_root, prop_dir = _setup_proposal(tmp_path, meta, doc)
    (vault_root / "flashcards").mkdir()
    loaded = load_proposal_directory(prop_dir, proposals_root=proposals_root)
    assert loaded.proposal is not None

    result = apply_proposal(
        loaded.proposal,
        vault_root=vault_root,
        applied_by="admin",
        applied_at="2026-07-13T03:00:00Z",
    )

    assert result.new_status == ProposalStatus.APPLIED
    assert (
        vault_root / "flashcards" / "driving-licence" / "traffic" / "right-of-way.md"
    ).read_text() == "hello"
