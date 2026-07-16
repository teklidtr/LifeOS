from dataclasses import replace
import re
import os
import json
import subprocess
import sys
from pathlib import Path

import pytest

from lifeos.proposals.recovery import (
    RecoveryConflictError,
    RecoveryCorruptStateError,
    RecoveryExpectedState,
    RecoveryFindingCode,
    RecoveryJournal,
    RecoveryLockUnavailableError,
    RecoveryOperation,
    RecoveryOperationType,
    RecoveryPhase,
    RecoveryStateFiles,
    RecoveryTransactionId,
    RecoveryUnavailableError,
    RecoveryValidationError,
    _deserialize_journal,
    _serialize_journal,
    acquire_recovery_lock,
    discover_recovery_state,
    generate_recovery_transaction_id,
    initialize_recovery_transaction,
    remove_completed_recovery_transaction,
    unresolved_recovery_journals,
    write_recovery_journal,
    load_recovery_journal,
)


def make_journal(
    transaction_id: str = "prop-20260714T120000Z-1234abcd-a1b2c3d4",
    proposal_id: str = "prop-20260714T120000Z-1234abcd",
    phase: RecoveryPhase = RecoveryPhase.PREPARED,
    ops: tuple[RecoveryOperation, ...] | None = None,
) -> RecoveryJournal:
    if ops is None:
        ops = (
            RecoveryOperation(
                operation_id="op-1",
                operation_type=RecoveryOperationType.REPLACE_GENERATED_FILE,
                target_path="wiki/target.md",
                expected_pre_state=RecoveryExpectedState.PRESENT,
                expected_pre_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                expected_pre_mode=0o644,
                staged_path="staged/wiki_target.md.tmp",
                staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
                staged_mode=0o644,
                backup_path="backups/wiki_target.md.bak",
                backup_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                staged_size=11,
                backup_size=10,
            ),
        )
    return RecoveryJournal(
        schema_version=2,
        transaction_id=RecoveryTransactionId(transaction_id),
        proposal_id=proposal_id,
        review_digest="sha256:2222222222222222222222222222222222222222222222222222222222222222",
        authorized_actor="user@example.com",
        phase=phase,
        created_at="2026-07-14T12:00:00Z",
        operations=ops,
        ownership_state=RecoveryStateFiles(
            expected_pre_state=RecoveryExpectedState.PRESENT,
            expected_pre_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            expected_pre_mode=0o644,
            staged_path="staged/ownership.json.tmp",
            staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            staged_mode=0o644,
            backup_path="backups/ownership.json.bak",
            backup_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            staged_size=11,
            backup_size=10,
        ),
        proposal_state=RecoveryStateFiles(
            expected_pre_state=RecoveryExpectedState.PRESENT,
            expected_pre_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            expected_pre_mode=0o644,
            staged_path="staged/proposal.md.tmp",
            staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            staged_mode=0o644,
            backup_path="backups/proposal.md.bak",
            backup_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            staged_size=11,
            backup_size=10,
        ),
    )


def test_journal_rejects_invalid_proposal_id() -> None:
    j = make_journal(proposal_id="invalid", transaction_id="invalid-a1b2c3d4")
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_journal_rejects_invalid_transaction_id() -> None:
    j = make_journal(transaction_id="invalid")
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_journal_rejects_transaction_id_for_another_proposal() -> None:
    j = make_journal(
        proposal_id="prop-20260714T120000Z-1234abcd",
        transaction_id="prop-20260714T120000Z-bbbbbbbb-a1b2c3d4",
    )
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_load_validates_transaction_id_before_filesystem_access(tmp_path: Path) -> None:
    with pytest.raises(RecoveryValidationError):
        load_recovery_journal(
            recovery_root=tmp_path,
            transaction_id=RecoveryTransactionId("invalid/id"),
        )


def test_cleanup_validates_transaction_id_before_filesystem_access(tmp_path: Path) -> None:
    with pytest.raises(RecoveryValidationError):
        remove_completed_recovery_transaction(
            recovery_root=tmp_path,
            transaction_id=RecoveryTransactionId("invalid/id"),
        )


def test_transaction_id_generation_uses_injected_suffix() -> None:
    def suffix() -> str:
        return "a1b2c3d4"

    tx_id = generate_recovery_transaction_id(
        proposal_id="prop-20260714T120000Z-1234abcd",
        suffix_factory=suffix,
    )
    assert tx_id == "prop-20260714T120000Z-1234abcd-a1b2c3d4"


def test_transaction_id_rejects_invalid_suffix() -> None:
    with pytest.raises(RecoveryValidationError):
        generate_recovery_transaction_id(
            proposal_id="prop-20260714T120000Z-1234abcd",
            suffix_factory=lambda: "short",
        )


def test_recovery_journal_round_trips_deterministically() -> None:
    j = make_journal()
    b = _serialize_journal(j)
    j2 = _deserialize_journal(b)
    assert j == j2
    b2 = _serialize_journal(j2)
    assert b == b2


def test_recovery_journal_serialization_is_byte_stable() -> None:
    j = make_journal()
    b = _serialize_journal(j)
    text = b.decode("utf-8")
    assert text.endswith("\n")
    assert " \n" not in text
    assert ":" in text
    assert ", " not in text


def test_recovery_journal_requires_review_digest() -> None:
    j = make_journal()
    object.__setattr__(j, "review_digest", "invalid")
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_recovery_journal_rejects_unknown_schema() -> None:
    j = make_journal()
    object.__setattr__(j, "schema_version", 3)
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_recovery_journal_rejects_corrupt_json() -> None:
    with pytest.raises(RecoveryCorruptStateError):
        _deserialize_journal(b"{corrupt")


def test_recovery_journal_rejects_absolute_target_path() -> None:
    op = RecoveryOperation(
        operation_id="op-1",
        operation_type=RecoveryOperationType.CREATE_GENERATED_FILE,
        target_path="/abs/path",
        expected_pre_state=RecoveryExpectedState.ABSENT,
        expected_pre_hash=None,
        expected_pre_mode=None,
                staged_path="staged/tmp",
        staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        staged_mode=0o644,
                backup_path=None,
        backup_hash=None,
    )
    j = make_journal(ops=(op,))
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_recovery_journal_rejects_parent_traversal() -> None:
    op = RecoveryOperation(
        operation_id="op-1",
        operation_type=RecoveryOperationType.CREATE_GENERATED_FILE,
        target_path="../target",
        expected_pre_state=RecoveryExpectedState.ABSENT,
        expected_pre_hash=None,
        expected_pre_mode=None,
                staged_path="staged/tmp",
        staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        staged_mode=0o644,
                backup_path=None,
        backup_hash=None,
    )
    j = make_journal(ops=(op,))
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_recovery_journal_rejects_backslash_path() -> None:
    op = RecoveryOperation(
        operation_id="op-1",
        operation_type=RecoveryOperationType.CREATE_GENERATED_FILE,
        target_path="foo\\bar",
        expected_pre_state=RecoveryExpectedState.ABSENT,
        expected_pre_hash=None,
        expected_pre_mode=None,
                staged_path="staged/tmp",
        staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        staged_mode=0o644,
                backup_path=None,
        backup_hash=None,
    )
    j = make_journal(ops=(op,))
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_recovery_journal_rejects_invalid_hash() -> None:
    op = RecoveryOperation(
        operation_id="op-1",
        operation_type=RecoveryOperationType.CREATE_GENERATED_FILE,
        target_path="target",
        expected_pre_state=RecoveryExpectedState.ABSENT,
        expected_pre_hash=None,
        expected_pre_mode=None,
        staged_path="staged/tmp",
        staged_hash="invalid",
        staged_mode=0o644,
        backup_path=None,
        backup_hash=None,
    )
    j = make_journal(ops=(op,))
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_recovery_journal_rejects_duplicate_operation_ids() -> None:
    op = RecoveryOperation(
        operation_id="op-1",
        operation_type=RecoveryOperationType.CREATE_GENERATED_FILE,
        target_path="target",
        expected_pre_state=RecoveryExpectedState.ABSENT,
        expected_pre_hash=None,
        expected_pre_mode=None,
                staged_path="staged/tmp",
        staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        staged_mode=0o644,
                backup_path=None,
        backup_hash=None,
    )
    j = make_journal(ops=(op, op))
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_recovery_journal_rejects_invalid_ownership_staged_path() -> None:
    j = make_journal()
    object.__setattr__(
        j, "ownership_state", replace(j.ownership_state, staged_path="staged/..")
    )
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_recovery_journal_rejects_invalid_ownership_backup_path() -> None:
    j = make_journal()
    object.__setattr__(
        j,
        "ownership_state",
        replace(j.ownership_state, staged_path="staged/file", backup_path="backups/.."),
    )
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_recovery_journal_rejects_invalid_proposal_staged_path() -> None:
    j = make_journal()
    object.__setattr__(
        j, "proposal_state", replace(j.proposal_state, staged_path="staged/..")
    )
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_recovery_journal_rejects_invalid_proposal_backup_path() -> None:
    j = make_journal()
    object.__setattr__(
        j,
        "proposal_state",
        replace(j.proposal_state, staged_path="staged/file", backup_path="backups/.."),
    )
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_journal_rejects_staged_path_outside_staged_directory() -> None:
    j = make_journal()
    object.__setattr__(
        j, "proposal_state", replace(j.proposal_state, staged_path="other/file")
    )
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_journal_rejects_backup_path_outside_backups_directory() -> None:
    j = make_journal()
    object.__setattr__(
        j,
        "proposal_state",
        replace(j.proposal_state, staged_path="staged/file", backup_path="other/file"),
    )
    with pytest.raises(RecoveryValidationError):
        _serialize_journal(j)


def test_initialize_requires_prepared_phase(tmp_path: Path) -> None:
    j = make_journal(phase=RecoveryPhase.COMPLETE)
    with pytest.raises(RecoveryValidationError):
        initialize_recovery_transaction(recovery_root=tmp_path, journal=j)


def test_initialize_rejects_existing_transaction(tmp_path: Path) -> None:
    j = make_journal()
    initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    with pytest.raises(RecoveryConflictError):
        initialize_recovery_transaction(recovery_root=tmp_path, journal=j)


def test_discovery_returns_transactions_in_deterministic_order(tmp_path: Path) -> None:
    j1 = make_journal("prop-20260714T120000Z-1234abcd-a1b2c3d4")
    # Must use same proposal ID base
    j2 = make_journal(
        "prop-20260714T120000Z-1234abcd-bbbbbbbb", proposal_id="prop-20260714T120000Z-1234abcd"
    )
    initialize_recovery_transaction(recovery_root=tmp_path, journal=j2)
    initialize_recovery_transaction(recovery_root=tmp_path, journal=j1)

    res = discover_recovery_state(recovery_root=tmp_path)
    assert len(res.journals) == 2
    assert res.journals[0].transaction_id == j1.transaction_id
    assert res.journals[1].transaction_id == j2.transaction_id


def test_discovery_reports_transaction_directory_without_journal(tmp_path: Path) -> None:
    d = tmp_path / "prop-20260714T120000Z-1234abcd-a1b2c3d4"
    d.mkdir()
    res = discover_recovery_state(recovery_root=tmp_path)
    assert len(res.findings) == 1
    assert res.findings[0].code == RecoveryFindingCode.DIR_WITHOUT_JOURNAL


def test_discovery_reports_transaction_id_mismatch(tmp_path: Path) -> None:
    j = make_journal("prop-20260714T120000Z-1234abcd-a1b2c3d4")
    d = tmp_path / "prop-20260714T120000Z-1234abcd-bbbbbbbb"
    d.mkdir()
    (d / "journal.json").write_bytes(_serialize_journal(j))
    (d / "staged").mkdir()
    (d / "backups").mkdir()
    res = discover_recovery_state(recovery_root=tmp_path)
    assert len(res.findings) == 1
    assert res.findings[0].code == RecoveryFindingCode.TRANSACTION_ID_MISMATCH


def test_discovery_reports_symlinked_transaction_directory(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    sym_dir = tmp_path / "prop-20260714T120000Z-1234abcd-a1b2c3d4"
    sym_dir.symlink_to(real_dir.name)
    res = discover_recovery_state(recovery_root=tmp_path)
    assert any(f.code == RecoveryFindingCode.SYMLINKED_DIR for f in res.findings)


def test_discovery_reports_symlinked_journal(tmp_path: Path) -> None:
    d = tmp_path / "prop-20260714T120000Z-1234abcd-a1b2c3d4"
    d.mkdir()
    real_f = tmp_path / "real.json"
    real_f.write_text("{}")
    (d / "journal.json").symlink_to(f"../{real_f.name}")
    res = discover_recovery_state(recovery_root=tmp_path)
    assert any(f.code == RecoveryFindingCode.SYMLINKED_JOURNAL for f in res.findings)


def test_unresolved_transaction_is_detected(tmp_path: Path) -> None:
    j = make_journal()
    initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    res = discover_recovery_state(recovery_root=tmp_path)
    unres = unresolved_recovery_journals(res)
    assert len(unres) == 1


def test_complete_transaction_is_not_unresolved(tmp_path: Path) -> None:
    j = make_journal()
    initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    j2 = make_journal(phase=RecoveryPhase.COMPLETE)
    write_recovery_journal(recovery_root=tmp_path, journal=j2)
    res = discover_recovery_state(recovery_root=tmp_path)
    unres = unresolved_recovery_journals(res)
    assert len(unres) == 0


def test_unresolved_recovery_journals_blocks_on_any_finding(tmp_path: Path) -> None:
    d = tmp_path / "prop-20260714T120000Z-1234abcd-a1b2c3d4"
    d.mkdir()
    res = discover_recovery_state(recovery_root=tmp_path)
    with pytest.raises(RecoveryCorruptStateError):
        unresolved_recovery_journals(res)


def test_cleanup_requires_complete_phase(tmp_path: Path) -> None:
    j = make_journal(phase=RecoveryPhase.PREPARED)
    initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    with pytest.raises(RecoveryValidationError):
        remove_completed_recovery_transaction(
            recovery_root=tmp_path, transaction_id=j.transaction_id
        )


def test_recovery_lock_prevents_concurrent_subprocess_holder(tmp_path: Path) -> None:
    code = f"""
import sys
import subprocess
from pathlib import Path
sys.path.insert(0, "{Path(__file__).parent.parent.parent / "src"}")
from lifeos.proposals.recovery import acquire_recovery_lock
import time

runtime = Path("{tmp_path}")
with acquire_recovery_lock(runtime_dir=runtime):
    print("READY", flush=True)
    time.sleep(10)
"""
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout
        p.stdout.readline()
        with pytest.raises(RecoveryLockUnavailableError):
            with acquire_recovery_lock(runtime_dir=tmp_path):
                _ = None
    finally:
        p.terminate()
        p.wait()


def test_recovery_lock_releases_after_context_exit(tmp_path: Path) -> None:
    with acquire_recovery_lock(runtime_dir=tmp_path):
        _ = None
    with acquire_recovery_lock(runtime_dir=tmp_path):
        _ = None
def test_recovery_lock_releases_after_process_exit(tmp_path: Path) -> None:
    code = f"""
import sys
from pathlib import Path
sys.path.insert(0, "{Path(__file__).parent.parent.parent / "src"}")
from lifeos.proposals.recovery import acquire_recovery_lock

runtime = Path("{tmp_path}")
with acquire_recovery_lock(runtime_dir=runtime):
    _ = None
"""
    subprocess.run([sys.executable, "-c", code], check=True)
    with acquire_recovery_lock(runtime_dir=tmp_path):
        _ = None
def test_recovery_lock_rejects_same_process_reentrancy(tmp_path: Path) -> None:
    with acquire_recovery_lock(runtime_dir=tmp_path):
        with pytest.raises(RecoveryLockUnavailableError):
            with acquire_recovery_lock(runtime_dir=tmp_path):
                _ = None
def test_recovery_lock_cleans_up_process_local_state_on_flock_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl

    def mock_flock(fd: int, op: int) -> None:
        raise OSError("Resource temporarily unavailable")

    monkeypatch.setattr(fcntl, "flock", mock_flock)

    with pytest.raises(RecoveryLockUnavailableError):
        with acquire_recovery_lock(runtime_dir=tmp_path):
            _ = None
    monkeypatch.undo()
    with acquire_recovery_lock(runtime_dir=tmp_path):
        _ = None
def test_write_rejects_symlinked_staged_directory(tmp_path: Path) -> None:
    j = make_journal()
    tx_dir = initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    real_staged = tmp_path / "real_staged"
    real_staged.mkdir()
    (tx_dir / "staged").rmdir()
    (tx_dir / "staged").symlink_to(real_staged)

    with pytest.raises(RecoveryCorruptStateError):
        write_recovery_journal(recovery_root=tmp_path, journal=j)


def test_write_rejects_symlinked_backups_directory(tmp_path: Path) -> None:
    j = make_journal()
    tx_dir = initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    real_backups = tmp_path / "real_backups"
    real_backups.mkdir()
    (tx_dir / "backups").rmdir()
    (tx_dir / "backups").symlink_to(real_backups)

    with pytest.raises(RecoveryCorruptStateError):
        write_recovery_journal(recovery_root=tmp_path, journal=j)


def test_load_rejects_symlinked_staged_directory(tmp_path: Path) -> None:
    j = make_journal()
    tx_dir = initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    real_staged = tmp_path / "real_staged"
    real_staged.mkdir()
    (tx_dir / "staged").rmdir()
    (tx_dir / "staged").symlink_to(real_staged)

    with pytest.raises(RecoveryCorruptStateError):
        load_recovery_journal(recovery_root=tmp_path, transaction_id=j.transaction_id)


def test_load_rejects_symlinked_backups_directory(tmp_path: Path) -> None:
    j = make_journal()
    tx_dir = initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    real_backups = tmp_path / "real_backups"
    real_backups.mkdir()
    (tx_dir / "backups").rmdir()
    (tx_dir / "backups").symlink_to(real_backups)

    with pytest.raises(RecoveryCorruptStateError):
        load_recovery_journal(recovery_root=tmp_path, transaction_id=j.transaction_id)


def test_cleanup_rejects_symlinked_staged_directory(tmp_path: Path) -> None:
    j = make_journal()
    tx_dir = initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    real_staged = tmp_path / "real_staged"
    real_staged.mkdir()
    (tx_dir / "staged").rmdir()
    (tx_dir / "staged").symlink_to(real_staged)

    with pytest.raises(RecoveryCorruptStateError):
        remove_completed_recovery_transaction(
            recovery_root=tmp_path, transaction_id=j.transaction_id
        )


def test_cleanup_rejects_symlinked_backups_directory(tmp_path: Path) -> None:
    j = make_journal()
    tx_dir = initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    real_backups = tmp_path / "real_backups"
    real_backups.mkdir()
    (tx_dir / "backups").rmdir()
    (tx_dir / "backups").symlink_to(real_backups)

    with pytest.raises(RecoveryCorruptStateError):
        remove_completed_recovery_transaction(
            recovery_root=tmp_path, transaction_id=j.transaction_id
        )


def test_initialize_rejects_symlinked_recovery_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real_root"
    real_root.mkdir()
    sym_root = tmp_path / "sym_root"
    sym_root.symlink_to(real_root)

    j = make_journal()
    with pytest.raises(RecoveryCorruptStateError):
        initialize_recovery_transaction(recovery_root=sym_root, journal=j)


def test_deserialize_rejects_non_object_root() -> None:
    with pytest.raises(RecoveryCorruptStateError):
        _deserialize_journal(b"[]")


def test_deserialize_rejects_non_list_operations() -> None:
    j = make_journal()
    b = _serialize_journal(j)
    data = json.loads(b)
    data["operations"] = {}
    with pytest.raises(RecoveryCorruptStateError):
        _deserialize_journal(json.dumps(data).encode("utf-8"))


def test_deserialize_rejects_non_object_operation() -> None:
    j = make_journal()
    b = _serialize_journal(j)
    data = json.loads(b)
    data["operations"] = ["invalid"]
    with pytest.raises(RecoveryCorruptStateError):
        _deserialize_journal(json.dumps(data).encode("utf-8"))


def test_deserialize_rejects_wrong_field_types() -> None:
    j = make_journal()
    b = _serialize_journal(j)
    data = json.loads(b)
    data["schema_version"] = "1"  # string instead of int
    with pytest.raises(RecoveryCorruptStateError):
        _deserialize_journal(json.dumps(data).encode("utf-8"))


def test_discovery_continues_after_structurally_invalid_journal(tmp_path: Path) -> None:
    tx_id_1 = "prop-20260714T120000Z-1234abcd-a1b2c3d4"
    d1 = tmp_path / tx_id_1
    d1.mkdir()
    (d1 / "journal.json").write_bytes(b"[]")
    (d1 / "staged").mkdir()
    (d1 / "backups").mkdir()

    j2 = make_journal("prop-20260714T120000Z-1234abcd-bbbbbbbb")
    initialize_recovery_transaction(recovery_root=tmp_path, journal=j2)

    res = discover_recovery_state(recovery_root=tmp_path)
    assert len(res.journals) == 1
    assert res.journals[0].transaction_id == j2.transaction_id
    assert any(
        f.code == RecoveryFindingCode.CORRUPT_JSON and f.transaction_name == tx_id_1
        for f in res.findings
    )


def test_discovery_reports_unexpected_recovery_lock_inside_root(tmp_path: Path) -> None:
    (tmp_path / "recovery.lock").touch()
    res = discover_recovery_state(recovery_root=tmp_path)
    assert any(
        f.code == RecoveryFindingCode.UNEXPECTED_FILE and f.transaction_name == "recovery.lock"
        for f in res.findings
    )


def test_discovery_continues_after_corrupt_entry(tmp_path: Path) -> None:
    j1 = make_journal("prop-20260714T120000Z-1234abcd-a1b2c3d4")
    initialize_recovery_transaction(recovery_root=tmp_path, journal=j1)

    (tmp_path / "corrupt_file").write_text("corrupt")

    res = discover_recovery_state(recovery_root=tmp_path)
    assert len(res.journals) == 1
    assert any(
        f.code == RecoveryFindingCode.UNEXPECTED_FILE and f.transaction_name == "corrupt_file"
        for f in res.findings
    )


def test_discovery_findings_do_not_contain_absolute_paths(tmp_path: Path) -> None:
    (tmp_path / "corrupt_file").write_text("corrupt")
    res = discover_recovery_state(recovery_root=tmp_path)
    assert all("/" not in f.transaction_name for f in res.findings)


def test_recovery_lock_cannot_be_released_early_by_caller(tmp_path: Path) -> None:
    with acquire_recovery_lock(runtime_dir=tmp_path) as lock:
        assert not hasattr(lock, "close")


def test_recovery_lock_guard_cleans_up_after_open_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    original_open = os.open

    def mock_open(*args: object, **kwargs: object) -> int:
        if str(args[0]).endswith("recovery.lock"):
            raise OSError("Mock open failure")
        return original_open(*args, **kwargs)  # type: ignore

    monkeypatch.setattr(os, "open", mock_open)

    with pytest.raises(RecoveryLockUnavailableError):
        with acquire_recovery_lock(runtime_dir=tmp_path):
            _ = None
    monkeypatch.undo()
    with acquire_recovery_lock(runtime_dir=tmp_path):
        _ = None
def test_recovery_lock_guard_cleans_up_after_flock_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl

    def mock_flock(fd: int, op: int) -> None:
        raise OSError("Resource temporarily unavailable")

    monkeypatch.setattr(fcntl, "flock", mock_flock)

    with pytest.raises(RecoveryLockUnavailableError):
        with acquire_recovery_lock(runtime_dir=tmp_path):
            _ = None
    monkeypatch.undo()
    with acquire_recovery_lock(runtime_dir=tmp_path):
        _ = None
def test_recovery_lock_guard_cleans_up_when_context_body_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        with acquire_recovery_lock(runtime_dir=tmp_path):
            raise ValueError("Test error")

    with acquire_recovery_lock(runtime_dir=tmp_path):
        _ = None
def test_write_rejects_symlinked_temporary_journal(tmp_path: Path) -> None:
    j = make_journal()
    tx_dir = initialize_recovery_transaction(recovery_root=tmp_path, journal=j)

    tmp_journal = tx_dir / "journal.json.tmp"
    real_f = tmp_path / "real.tmp"
    real_f.write_text("{}")
    tmp_journal.symlink_to(real_f)

    with pytest.raises(RecoveryCorruptStateError):
        write_recovery_journal(recovery_root=tmp_path, journal=j)

    assert tx_dir.exists()
    assert (tx_dir / "journal.json").exists()


@pytest.fixture
def base_journal() -> RecoveryJournal:
    return make_journal()


def test_discovery_absent_root_returns_empty_without_creating_it(tmp_path: Path) -> None:
    root = tmp_path / "recovery"
    result = discover_recovery_state(recovery_root=root)
    assert result.journals == ()
    assert result.findings == ()
    assert not root.exists()


def test_discovery_rejects_symlinked_recovery_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    sym = tmp_path / "sym"
    sym.symlink_to(real)
    with pytest.raises(RecoveryCorruptStateError, match="Invalid recovery root"):
        discover_recovery_state(recovery_root=sym)


def test_discovery_rejects_recovery_root_that_is_a_file(tmp_path: Path) -> None:
    root = tmp_path / "recovery"
    root.touch()
    with pytest.raises(RecoveryCorruptStateError, match="Invalid recovery root"):
        discover_recovery_state(recovery_root=root)


def test_discovery_fails_closed_when_root_cannot_be_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "recovery"
    root.mkdir()

    def mock_iterdir(*args: object, **kwargs: object) -> None:
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "iterdir", mock_iterdir)
    with pytest.raises(RecoveryUnavailableError, match="Failed to list recovery root"):
        discover_recovery_state(recovery_root=root)


def test_load_rejects_missing_staged_directory(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    root = tmp_path / "recovery"
    root.mkdir()
    tx_id = base_journal.transaction_id
    tx_dir = root / tx_id
    tx_dir.mkdir()
    (tx_dir / "journal.json").touch()
    (tx_dir / "backups").mkdir()
    with pytest.raises(
        RecoveryCorruptStateError, match="Staged must be a directory|Path does not exist"
    ):
        load_recovery_journal(recovery_root=root, transaction_id=tx_id)


def test_load_rejects_missing_backups_directory(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    root = tmp_path / "recovery"
    root.mkdir()
    tx_id = base_journal.transaction_id
    tx_dir = root / tx_id
    tx_dir.mkdir()
    (tx_dir / "journal.json").touch()
    (tx_dir / "staged").mkdir()
    with pytest.raises(
        RecoveryCorruptStateError, match="Backups must be a directory|Path does not exist"
    ):
        load_recovery_journal(recovery_root=root, transaction_id=tx_id)


def test_load_rejects_journal_directory(tmp_path: Path, base_journal: RecoveryJournal) -> None:
    root = tmp_path / "recovery"
    root.mkdir()
    tx_id = base_journal.transaction_id
    tx_dir = root / tx_id
    tx_dir.mkdir()
    (tx_dir / "journal.json").mkdir()
    (tx_dir / "staged").mkdir()
    (tx_dir / "backups").mkdir()
    with pytest.raises(RecoveryCorruptStateError, match="Journal must be a regular file"):
        load_recovery_journal(recovery_root=root, transaction_id=tx_id)


def test_load_rejects_staged_regular_file(tmp_path: Path, base_journal: RecoveryJournal) -> None:
    root = tmp_path / "recovery"
    root.mkdir()
    tx_id = base_journal.transaction_id
    tx_dir = root / tx_id
    tx_dir.mkdir()
    (tx_dir / "journal.json").touch()
    (tx_dir / "staged").touch()
    (tx_dir / "backups").mkdir()
    with pytest.raises(
        RecoveryCorruptStateError, match="Staged must be a directory|Path does not exist"
    ):
        load_recovery_journal(recovery_root=root, transaction_id=tx_id)


def test_load_rejects_backups_regular_file(tmp_path: Path, base_journal: RecoveryJournal) -> None:
    root = tmp_path / "recovery"
    root.mkdir()
    tx_id = base_journal.transaction_id
    tx_dir = root / tx_id
    tx_dir.mkdir()
    (tx_dir / "journal.json").touch()
    (tx_dir / "staged").mkdir()
    (tx_dir / "backups").touch()
    with pytest.raises(
        RecoveryCorruptStateError, match="Backups must be a directory|Path does not exist"
    ):
        load_recovery_journal(recovery_root=root, transaction_id=tx_id)


def test_write_rejects_incomplete_transaction_layout(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    root = tmp_path / "recovery"
    root.mkdir()
    tx_id = base_journal.transaction_id
    tx_dir = root / tx_id
    tx_dir.mkdir()
    (tx_dir / "journal.json").touch()
    # Missing staged and backups
    with pytest.raises(
        RecoveryCorruptStateError, match="Staged must be a directory|Path does not exist"
    ):
        write_recovery_journal(recovery_root=root, journal=base_journal)


def test_cleanup_rejects_incomplete_transaction_layout(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    from lifeos.proposals.recovery import remove_completed_recovery_transaction

    root = tmp_path / "recovery"
    root.mkdir()
    tx_id = base_journal.transaction_id
    tx_dir = root / tx_id
    tx_dir.mkdir()
    (tx_dir / "journal.json").touch()
    # Missing staged and backups
    with pytest.raises(
        RecoveryCorruptStateError, match="Staged must be a directory|Path does not exist"
    ):
        remove_completed_recovery_transaction(recovery_root=root, transaction_id=tx_id)


def test_discovery_reports_broken_transaction_symlink(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    root = tmp_path / "recovery"
    root.mkdir()
    tx_id = base_journal.transaction_id
    sym = root / tx_id
    sym.symlink_to(root / "nonexistent")
    result = discover_recovery_state(recovery_root=root)
    assert len(result.findings) == 1
    assert result.findings[0].code == RecoveryFindingCode.SYMLINKED_DIR
    assert result.findings[0].transaction_name == tx_id


def test_discovery_reports_broken_journal_symlink(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    root = tmp_path / "recovery"
    root.mkdir()
    tx_id = base_journal.transaction_id
    tx_dir = root / tx_id
    tx_dir.mkdir()
    sym = tx_dir / "journal.json"
    sym.symlink_to(tx_dir / "nonexistent")
    result = discover_recovery_state(recovery_root=root)
    assert len(result.findings) == 1
    assert result.findings[0].code == RecoveryFindingCode.SYMLINKED_JOURNAL
    assert result.findings[0].transaction_name == tx_id


def test_journal_rejects_boolean_schema_version(base_journal: RecoveryJournal) -> None:
    with pytest.raises(RecoveryValidationError, match="schema_version must be exact int"):
        _serialize_journal(replace(base_journal, schema_version=True))


def test_journal_rejects_non_string_review_digest(base_journal: RecoveryJournal) -> None:
    with pytest.raises(RecoveryValidationError, match="review_digest must be string"):
        _serialize_journal(replace(base_journal, review_digest=123))  # type: ignore


def test_journal_rejects_non_string_created_at(base_journal: RecoveryJournal) -> None:
    with pytest.raises(RecoveryValidationError, match="created_at must be string"):
        _serialize_journal(replace(base_journal, created_at=None))  # type: ignore


def test_journal_rejects_non_string_actor(base_journal: RecoveryJournal) -> None:
    with pytest.raises(RecoveryValidationError, match="authorized_actor must be string"):
        _serialize_journal(replace(base_journal, authorized_actor=1))  # type: ignore


def test_journal_rejects_invalid_phase_type(base_journal: RecoveryJournal) -> None:
    with pytest.raises(RecoveryValidationError, match="Invalid phase type"):
        _serialize_journal(replace(base_journal, phase="prepared"))  # type: ignore


def test_journal_rejects_non_tuple_operations(base_journal: RecoveryJournal) -> None:
    with pytest.raises(RecoveryValidationError, match="Operations must be exact tuple"):
        _serialize_journal(replace(base_journal, operations=list(base_journal.operations)))  # type: ignore


def test_journal_rejects_non_operation_member(base_journal: RecoveryJournal) -> None:
    with pytest.raises(RecoveryValidationError, match="Operation member must be RecoveryOperation"):
        _serialize_journal(replace(base_journal, operations=(None,)))  # type: ignore


def test_journal_rejects_unhashable_operation_id(base_journal: RecoveryJournal) -> None:
    op = base_journal.operations[0]
    with pytest.raises(RecoveryValidationError, match="Invalid operation ID"):
        _serialize_journal(replace(base_journal, operations=(replace(op, operation_id=None),)))  # type: ignore
    with pytest.raises(RecoveryValidationError, match="Invalid operation ID"):
        _serialize_journal(replace(base_journal, operations=(replace(op, operation_id=""),)))


def test_journal_rejects_non_string_staged_path(base_journal: RecoveryJournal) -> None:
    op = base_journal.operations[0]
    with pytest.raises(RecoveryValidationError, match="Path must be a string"):
        _serialize_journal(replace(base_journal, operations=(replace(op, staged_path=None),)))  # type: ignore


def test_transaction_id_generator_rejects_non_string_suffix() -> None:
    with pytest.raises(RecoveryValidationError, match="Suffix must be a string"):
        generate_recovery_transaction_id(
            proposal_id="prop-20231010T120000Z-12345678", suffix_factory=lambda: None  # type: ignore
        )


def test_journal_rejects_impossible_created_at(base_journal: RecoveryJournal) -> None:
    with pytest.raises(RecoveryValidationError, match="Invalid created_at"):
        _serialize_journal(replace(base_journal, created_at="2024-13-45T25:99:99Z"))


def test_journal_rejects_created_at_with_offset(base_journal: RecoveryJournal) -> None:
    with pytest.raises(RecoveryValidationError, match="Invalid created_at"):
        _serialize_journal(replace(base_journal, created_at="2024-01-01T12:00:00+00:00"))


def test_journal_rejects_created_at_with_fractional_seconds(base_journal: RecoveryJournal) -> None:
    with pytest.raises(RecoveryValidationError, match="Invalid created_at"):
        _serialize_journal(replace(base_journal, created_at="2024-01-01T12:00:00.123Z"))


def test_recovery_journal_serializes_unicode_without_ascii_escaping(
    base_journal: RecoveryJournal,
) -> None:
    journal = replace(base_journal, authorized_actor="test \u2603 snowman")
    data = _serialize_journal(journal)
    text = data.decode("utf-8")
    assert "\\u2603" not in text
    assert "test \u2603 snowman" in text


def test_recovery_lock_rejects_symlinked_lock_file(tmp_path: Path) -> None:
    rt = tmp_path / "rt"
    rt.mkdir()
    lock_file = rt / "recovery.lock"
    lock_file.symlink_to(rt / "other")
    with pytest.raises(RecoveryLockUnavailableError, match="Symlinked lock file not permitted"):
        with acquire_recovery_lock(runtime_dir=rt):
            _ = None
def test_recovery_lock_does_not_modify_symlink_target(tmp_path: Path) -> None:
    rt = tmp_path / "rt"
    rt.mkdir()
    lock_file = rt / "recovery.lock"
    target = rt / "other"
    target.write_bytes(b"testdata")
    lock_file.symlink_to(target)
    with pytest.raises(RecoveryLockUnavailableError, match="Symlinked lock file not permitted"):
        with acquire_recovery_lock(runtime_dir=rt):
            _ = None
    assert target.read_bytes() == b"testdata"


def test_write_failure_preserves_original_journal(
    tmp_path: Path, base_journal: RecoveryJournal, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "recovery"
    initialize_recovery_transaction(recovery_root=root, journal=base_journal)

    def mock_replace(*args: object, **kwargs: object) -> None:
        raise OSError("Permission denied")

    monkeypatch.setattr(os, "replace", mock_replace)

    with pytest.raises(RecoveryUnavailableError, match="Failed to write journal"):
        write_recovery_journal(
            recovery_root=root, journal=replace(base_journal, phase=RecoveryPhase.TARGETS_INSTALLED)
        )

    # Original should be untouched
    journal_path = root / base_journal.transaction_id / "journal.json"
    content = journal_path.read_bytes()
    assert b"prepared" in content
    assert b"targets_installed" not in content


def test_write_failure_removes_temporary_journal(
    tmp_path: Path, base_journal: RecoveryJournal, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "recovery"
    initialize_recovery_transaction(recovery_root=root, journal=base_journal)

    def mock_replace(*args: object, **kwargs: object) -> None:
        raise OSError("Permission denied")

    monkeypatch.setattr(os, "replace", mock_replace)

    with pytest.raises(RecoveryUnavailableError, match="Failed to write journal"):
        write_recovery_journal(
            recovery_root=root, journal=replace(base_journal, phase=RecoveryPhase.TARGETS_INSTALLED)
        )

    tmp_path_file = root / base_journal.transaction_id / "journal.json.tmp"
    assert not tmp_path_file.exists()


def test_write_failure_does_not_delete_transaction(
    tmp_path: Path, base_journal: RecoveryJournal, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "recovery"
    initialize_recovery_transaction(recovery_root=root, journal=base_journal)

    def mock_replace(*args: object, **kwargs: object) -> None:
        raise OSError("Permission denied")

    monkeypatch.setattr(os, "replace", mock_replace)

    with pytest.raises(RecoveryUnavailableError, match="Failed to write journal"):
        write_recovery_journal(
            recovery_root=root, journal=replace(base_journal, phase=RecoveryPhase.TARGETS_INSTALLED)
        )

    tx_dir = root / base_journal.transaction_id
    assert tx_dir.is_dir()
    assert (tx_dir / "journal.json").is_file()


def test_deserialize_rejects_boolean_schema_version(base_journal: RecoveryJournal) -> None:
    data = _serialize_journal(base_journal)
    text = data.decode("utf-8").replace('"schema_version":2', '"schema_version":true')
    with pytest.raises(
        RecoveryCorruptStateError,
        match="Invalid schema version type",
    ):
        _deserialize_journal(text.encode("utf-8"))


def test_deserialize_rejects_integer_review_digest(base_journal: RecoveryJournal) -> None:
    data = _serialize_journal(base_journal)
    text = data.decode("utf-8").replace(f'"{base_journal.review_digest}"', "1234")
    with pytest.raises(
        RecoveryCorruptStateError,
        match="Invalid field value|Invalid field type|Logical validation failed",
    ):
        _deserialize_journal(text.encode("utf-8"))


def test_deserialize_rejects_invalid_operation_field_types(base_journal: RecoveryJournal) -> None:
    data = _serialize_journal(base_journal)
    text = re.sub(r'"operation_id":"[^"]+"', '"operation_id":123', data.decode("utf-8"))
    with pytest.raises(
        RecoveryCorruptStateError,
        match="Invalid field type|Invalid field value|Logical validation failed",
    ):
        _deserialize_journal(text.encode("utf-8"))


def test_discovery_continues_after_type_invalid_journal(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    root = tmp_path / "recovery"
    initialize_recovery_transaction(recovery_root=root, journal=base_journal)

    tx2_id = RecoveryTransactionId("prop-20231010T120000Z-12345678-bbbbbbbb")
    j2 = replace(base_journal, transaction_id=tx2_id, proposal_id="prop-20231010T120000Z-12345678")
    initialize_recovery_transaction(recovery_root=root, journal=j2)

    data = _serialize_journal(base_journal)
    text = data.decode("utf-8").replace('"schema_version":2', '"schema_version":true')
    (root / base_journal.transaction_id / "journal.json").write_bytes(text.encode("utf-8"))

    result = discover_recovery_state(recovery_root=root)
    assert len(result.journals) == 1
    assert result.journals[0].transaction_id == tx2_id
    assert len(result.findings) == 1
    assert result.findings[0].code == RecoveryFindingCode.CORRUPT_JSON
    assert result.findings[0].transaction_name == base_journal.transaction_id


def test_deserialize_rejects_invalid_transaction_id_as_corrupt_state(
    base_journal: RecoveryJournal,
) -> None:
    from lifeos.proposals.recovery import (
        _serialize_journal,
        _deserialize_journal,
        RecoveryCorruptStateError,
    )

    data = _serialize_journal(base_journal)
    import re

    text = re.sub(r'"transaction_id":"[^"]+"', '"transaction_id":"invalid"', data.decode("utf-8"))
    with pytest.raises(RecoveryCorruptStateError, match="Invalid persisted transaction_id"):
        _deserialize_journal(text.encode("utf-8"))


def test_discovery_continues_after_invalid_persisted_transaction_id(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    from lifeos.proposals.recovery import (
        initialize_recovery_transaction,
        discover_recovery_state,
        RecoveryFindingCode,
        RecoveryTransactionId,
    )
    from dataclasses import replace

    root = tmp_path / "recovery"
    initialize_recovery_transaction(recovery_root=root, journal=base_journal)

    tx2_id = RecoveryTransactionId("prop-20231010T120000Z-12345678-bbbbbbbb")
    j2 = replace(base_journal, transaction_id=tx2_id, proposal_id="prop-20231010T120000Z-12345678")
    initialize_recovery_transaction(recovery_root=root, journal=j2)

    # Corrupt j2's persisted transaction_id
    j2_path = root / tx2_id / "journal.json"
    import re

    bad_text = re.sub(
        r'"transaction_id":"[^"]+"',
        '"transaction_id":"invalid"',
        j2_path.read_text(encoding="utf-8"),
    )
    j2_path.write_text(bad_text, encoding="utf-8")

    result = discover_recovery_state(recovery_root=root)
    assert len(result.journals) == 1
    assert result.journals[0] == base_journal

    assert len(result.findings) == 1
    assert result.findings[0].code == RecoveryFindingCode.CORRUPT_JSON
    assert result.findings[0].transaction_name == str(tx2_id)


def test_discovery_reports_missing_staged_as_invalid_layout(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    from lifeos.proposals.recovery import (
        initialize_recovery_transaction,
        discover_recovery_state,
        RecoveryFindingCode,
    )
    import shutil

    root = tmp_path / "recovery"
    initialize_recovery_transaction(recovery_root=root, journal=base_journal)

    shutil.rmtree(root / base_journal.transaction_id / "staged")
    result = discover_recovery_state(recovery_root=root)
    assert len(result.journals) == 0
    assert len(result.findings) == 1
    assert result.findings[0].code == RecoveryFindingCode.INVALID_LAYOUT


def test_discovery_reports_missing_backups_as_invalid_layout(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    from lifeos.proposals.recovery import (
        initialize_recovery_transaction,
        discover_recovery_state,
        RecoveryFindingCode,
    )
    import shutil

    root = tmp_path / "recovery"
    initialize_recovery_transaction(recovery_root=root, journal=base_journal)

    shutil.rmtree(root / base_journal.transaction_id / "backups")
    result = discover_recovery_state(recovery_root=root)
    assert len(result.journals) == 0
    assert len(result.findings) == 1
    assert result.findings[0].code == RecoveryFindingCode.INVALID_LAYOUT


def test_discovery_reports_symlinked_staged_as_invalid_layout(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    from lifeos.proposals.recovery import (
        initialize_recovery_transaction,
        discover_recovery_state,
        RecoveryFindingCode,
    )
    import shutil
    import os

    root = tmp_path / "recovery"
    initialize_recovery_transaction(recovery_root=root, journal=base_journal)

    shutil.rmtree(root / base_journal.transaction_id / "staged")
    os.symlink(".", root / base_journal.transaction_id / "staged")

    result = discover_recovery_state(recovery_root=root)
    assert len(result.journals) == 0
    assert len(result.findings) == 1
    assert result.findings[0].code == RecoveryFindingCode.INVALID_LAYOUT


def test_discovery_reports_symlinked_backups_as_invalid_layout(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    from lifeos.proposals.recovery import (
        initialize_recovery_transaction,
        discover_recovery_state,
        RecoveryFindingCode,
    )
    import shutil
    import os

    root = tmp_path / "recovery"
    initialize_recovery_transaction(recovery_root=root, journal=base_journal)

    shutil.rmtree(root / base_journal.transaction_id / "backups")
    os.symlink(".", root / base_journal.transaction_id / "backups")

    result = discover_recovery_state(recovery_root=root)
    assert len(result.journals) == 0
    assert len(result.findings) == 1
    assert result.findings[0].code == RecoveryFindingCode.INVALID_LAYOUT


def test_discovery_continues_after_invalid_layout(
    tmp_path: Path, base_journal: RecoveryJournal
) -> None:
    from lifeos.proposals.recovery import (
        initialize_recovery_transaction,
        discover_recovery_state,
        RecoveryFindingCode,
        RecoveryTransactionId,
    )
    from dataclasses import replace
    import shutil

    root = tmp_path / "recovery"
    initialize_recovery_transaction(recovery_root=root, journal=base_journal)

    tx2_id = RecoveryTransactionId("prop-20231010T120000Z-12345678-bbbbbbbb")
    j2 = replace(base_journal, transaction_id=tx2_id, proposal_id="prop-20231010T120000Z-12345678")
    initialize_recovery_transaction(recovery_root=root, journal=j2)

    shutil.rmtree(root / tx2_id / "backups")

    result = discover_recovery_state(recovery_root=root)
    assert len(result.journals) == 1
    assert result.journals[0] == base_journal

    assert len(result.findings) == 1
    assert result.findings[0].code == RecoveryFindingCode.INVALID_LAYOUT
    assert result.findings[0].transaction_name == str(tx2_id)

def test_discovery_rejects_broken_recovery_root_symlink(tmp_path: Path) -> None:
    from lifeos.proposals.recovery import discover_recovery_state, RecoveryCorruptStateError
    import os

    root = tmp_path / "recovery"
    target = tmp_path / "does_not_exist"
    os.symlink(target, root)

    with pytest.raises(RecoveryCorruptStateError, match="Invalid recovery root"):
        discover_recovery_state(recovery_root=root)

def test_journal_rejects_non_zero_padded_created_at(base_journal: RecoveryJournal) -> None:
    from lifeos.proposals.recovery import _serialize_journal, RecoveryValidationError
    from dataclasses import replace
    import pytest

    with pytest.raises(RecoveryValidationError, match="Invalid created_at"):
        _serialize_journal(replace(base_journal, created_at="2026-7-14T12:00:00Z"))

    with pytest.raises(RecoveryValidationError, match="Invalid created_at"):
        _serialize_journal(replace(base_journal, created_at="2026-07-4T12:00:00Z"))


def test_recovery_schema_two_round_trips() -> None:
    journal = make_journal()
    assert journal.schema_version == 2
    raw = _serialize_journal(journal)
    j2 = _deserialize_journal(raw)
    assert j2 == journal

def test_recovery_schema_one_is_rejected() -> None:
    from lifeos.proposals.recovery import RecoveryUnknownSchemaError
    raw = _serialize_journal(make_journal()).decode("utf-8")
    bad_raw = raw.replace('"schema_version":2', '"schema_version":1')
    with pytest.raises(RecoveryUnknownSchemaError, match="Unknown schema version"):
        _deserialize_journal(bad_raw.encode("utf-8"))

def test_recovery_operation_records_expected_pre_mode() -> None:
    op = RecoveryOperation(
        operation_id="op-1",
        operation_type=RecoveryOperationType.REPLACE_GENERATED_FILE,
        target_path="wiki/target.md",
        expected_pre_state=RecoveryExpectedState.PRESENT,
        expected_pre_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        expected_pre_mode=0o644,
        staged_path="staged/wiki_target.md.tmp",
        staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        staged_mode=0o644,
        backup_path="backups/wiki_target.md.bak",
        backup_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )
    assert op.expected_pre_mode == 0o644

def test_recovery_operation_records_staged_mode() -> None:
    op = RecoveryOperation(
        operation_id="op-1",
        operation_type=RecoveryOperationType.REPLACE_GENERATED_FILE,
        target_path="wiki/target.md",
        expected_pre_state=RecoveryExpectedState.PRESENT,
        expected_pre_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        expected_pre_mode=0o644,
        staged_path="staged/wiki_target.md.tmp",
        staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        staged_mode=0o755,
        backup_path="backups/wiki_target.md.bak",
        backup_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )
    assert op.staged_mode == 0o755

def test_recovery_state_files_require_pre_mode_for_present_state() -> None:
    with pytest.raises(RecoveryValidationError, match="expected_pre_mode must be an int"):
        RecoveryStateFiles(
            expected_pre_state=RecoveryExpectedState.PRESENT,
            expected_pre_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            expected_pre_mode=None,
            staged_path="staged/test.tmp",
            staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            staged_mode=0o644,
            backup_path="backups/test.bak",
            backup_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        )

def test_recovery_state_files_forbid_pre_mode_for_absent_state() -> None:
    with pytest.raises(RecoveryValidationError, match="expected_pre_mode must be None"):
        RecoveryStateFiles(
            expected_pre_state=RecoveryExpectedState.ABSENT,
            expected_pre_hash=None,
            expected_pre_mode=0o644,
            staged_path="staged/test.tmp",
            staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            staged_mode=0o644,
            backup_path=None,
            backup_hash=None,
        )

def test_recovery_state_files_require_staged_hash() -> None:
    with pytest.raises(RecoveryValidationError, match="staged_hash"):
        RecoveryStateFiles(
            expected_pre_state=RecoveryExpectedState.ABSENT,
            expected_pre_hash=None,
            expected_pre_mode=None,
            staged_path="staged/test.tmp",
            staged_hash=None, # type: ignore
            staged_mode=0o644,
            backup_path=None,
            backup_hash=None,
        )

def test_recovery_state_files_require_backup_for_present_pre_state() -> None:
    with pytest.raises(RecoveryValidationError, match="backup_hash must be a string for PRESENT"):
        RecoveryStateFiles(
            expected_pre_state=RecoveryExpectedState.PRESENT,
            expected_pre_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            expected_pre_mode=0o644,
            staged_path="staged/test.tmp",
            staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            staged_mode=0o644,
            backup_path=None,
            backup_hash=None,
        )

def test_recovery_state_files_for_absent_pre_state_forbid_backup() -> None:
    with pytest.raises(RecoveryValidationError, match="backup_hash must be None"):
        RecoveryStateFiles(
            expected_pre_state=RecoveryExpectedState.ABSENT,
            expected_pre_hash=None,
            expected_pre_mode=None,
            staged_path="staged/test.tmp",
            staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            staged_mode=0o644,
            backup_path="backups/test.bak",
            backup_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        )

def test_recovery_rejects_boolean_permission_mode() -> None:
    with pytest.raises(RecoveryValidationError, match="Invalid permission mode type"):
        RecoveryStateFiles(
            expected_pre_state=RecoveryExpectedState.ABSENT,
            expected_pre_hash=None,
            expected_pre_mode=None,
            staged_path="staged/test.tmp",
            staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            staged_mode=True, # type: ignore
            backup_path=None,
            backup_hash=None,
        )

def test_recovery_rejects_negative_permission_mode() -> None:
    with pytest.raises(RecoveryValidationError, match="Invalid permission mode value"):
        RecoveryStateFiles(
            expected_pre_state=RecoveryExpectedState.ABSENT,
            expected_pre_hash=None,
            expected_pre_mode=None,
            staged_path="staged/test.tmp",
            staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            staged_mode=-1,
            backup_path=None,
            backup_hash=None,
        )

def test_recovery_rejects_permission_mode_above_0o7777() -> None:
    with pytest.raises(RecoveryValidationError, match="Invalid permission mode value"):
        RecoveryStateFiles(
            expected_pre_state=RecoveryExpectedState.ABSENT,
            expected_pre_hash=None,
            expected_pre_mode=None,
            staged_path="staged/test.tmp",
            staged_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            staged_mode=0o10000,
            backup_path=None,
            backup_hash=None,
        )

def test_recovery_schema_two_preserves_modes_deterministically() -> None:
    j = make_journal()
    raw = _serialize_journal(j)
    assert b'"staged_mode":420' in raw or b'"staged_mode": 420' in raw

def test_remove_rolled_back_transaction_rejects_complete_phase(tmp_path: Path) -> None:
    from lifeos.proposals.recovery import initialize_recovery_transaction, remove_rolled_back_recovery_transaction
    j = make_journal(phase=RecoveryPhase.COMPLETE)
    try:
        initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    except Exception:
        _ = None
    # We must write it manually because initialize rejects non-PREPARED phase.
    tx_dir = tmp_path / j.transaction_id
    tx_dir.mkdir(parents=True, exist_ok=True)
    (tx_dir / "staged").mkdir()
    (tx_dir / "backups").mkdir()
    from lifeos.proposals.recovery import _serialize_journal
    (tx_dir / "journal.json").write_bytes(_serialize_journal(j))
    with pytest.raises(RecoveryValidationError, match="Cannot remove complete transaction"):
        remove_rolled_back_recovery_transaction(transaction_id=j.transaction_id, recovery_root=tmp_path)

def test_remove_rolled_back_transaction_removes_unresolved_transaction(tmp_path: Path) -> None:
    from lifeos.proposals.recovery import initialize_recovery_transaction, remove_rolled_back_recovery_transaction
    j = make_journal(phase=RecoveryPhase.PREPARED)
    tx_dir = initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    remove_rolled_back_recovery_transaction(transaction_id=j.transaction_id, recovery_root=tmp_path)
    assert not tx_dir.exists()

def test_remove_rolled_back_transaction_rejects_symlinked_layout(tmp_path: Path) -> None:
    from lifeos.proposals.recovery import initialize_recovery_transaction, remove_rolled_back_recovery_transaction
    j = make_journal(phase=RecoveryPhase.PREPARED)
    tx_dir = initialize_recovery_transaction(recovery_root=tmp_path, journal=j)
    import shutil
    shutil.rmtree(tx_dir / "staged")
    import os
    os.symlink(".", tx_dir / "staged")
    with pytest.raises(RecoveryCorruptStateError):
        remove_rolled_back_recovery_transaction(transaction_id=j.transaction_id, recovery_root=tmp_path)

def test_recovery_unknown_future_schema_is_rejected() -> None:
    from lifeos.proposals.recovery import RecoveryUnknownSchemaError
    raw = _serialize_journal(make_journal()).decode("utf-8")
    bad_raw = raw.replace('"schema_version":2', '"schema_version":3')
    with pytest.raises(RecoveryUnknownSchemaError, match="Unknown schema version"):
        _deserialize_journal(bad_raw.encode("utf-8"))

def test_deserialize_rejects_float_schema_version(base_journal: RecoveryJournal) -> None:
    data = _serialize_journal(base_journal)
    text = data.decode("utf-8").replace('"schema_version":2', '"schema_version":2.0')
    with pytest.raises(RecoveryCorruptStateError, match="Invalid schema version type"):
        _deserialize_journal(text.encode("utf-8"))

def test_deserialize_rejects_string_schema_version(base_journal: RecoveryJournal) -> None:
    data = _serialize_journal(base_journal)
    text = data.decode("utf-8").replace('"schema_version":2', '"schema_version":"2"')
    with pytest.raises(RecoveryCorruptStateError, match="Invalid schema version type"):
        _deserialize_journal(text.encode("utf-8"))

def test_deserialize_rejects_missing_schema_version(base_journal: RecoveryJournal) -> None:
    import json
    data = _serialize_journal(base_journal)
    obj = json.loads(data.decode("utf-8"))
    del obj["schema_version"]
    text = json.dumps(obj)
    with pytest.raises(RecoveryCorruptStateError, match="Missing schema version"):
        _deserialize_journal(text.encode("utf-8"))


@pytest.mark.parametrize(
    "operation_type",
    [
        RecoveryOperationType.CREATE_FILE,
        RecoveryOperationType.PATCH_HUMAN_FILE,
        RecoveryOperationType.CREATE_GENERATED_FILE,
        RecoveryOperationType.REPLACE_GENERATED_FILE,
        RecoveryOperationType.REPLACE_MANAGED_BLOCK,
    ],
)
def test_recovery_schema_accepts_every_consequential_operation(
    operation_type: RecoveryOperationType,
) -> None:
    creation = operation_type in (
        RecoveryOperationType.CREATE_FILE,
        RecoveryOperationType.CREATE_GENERATED_FILE,
    )
    operation = RecoveryOperation(
        operation_id="op-1",
        operation_type=operation_type,
        target_path="wiki/target.md",
        expected_pre_state=(
            RecoveryExpectedState.ABSENT if creation else RecoveryExpectedState.PRESENT
        ),
        expected_pre_hash=None if creation else "sha256:" + "0" * 64,
        expected_pre_mode=None if creation else 0o644,
        staged_path="staged/target",
        staged_hash="sha256:" + "1" * 64,
        staged_mode=0o644,
        backup_path=None if creation else "backups/target",
        backup_hash=None if creation else "sha256:" + "0" * 64,
        staged_size=11,
        backup_size=None if creation else 10,
    )

    journal = make_journal(ops=(operation,))
    assert _deserialize_journal(_serialize_journal(journal)) == journal


def test_recovery_schema_round_trips_artifact_sizes() -> None:
    journal = make_journal()

    recovered = _deserialize_journal(_serialize_journal(journal))

    assert recovered.operations[0].staged_size == 11
    assert recovered.operations[0].backup_size == 10
    assert recovered.ownership_state.staged_size == 11
    assert recovered.ownership_state.backup_size == 10
    assert recovered.proposal_state.staged_size == 11
    assert recovered.proposal_state.backup_size == 10


def test_deserialize_rejects_missing_artifact_size() -> None:
    raw = json.loads(_serialize_journal(make_journal()))
    del raw["operations"][0]["staged_size"]

    with pytest.raises(RecoveryCorruptStateError, match="Missing field"):
        _deserialize_journal(json.dumps(raw).encode())
