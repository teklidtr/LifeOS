"""Tests for the lifeos status command."""

import hashlib
import json
import os
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from lifeos.cli import main
from lifeos.registry import Registry


def snapshot_dir(path: Path) -> dict[str, dict]:
    """Capture a snapshot of a directory to verify read-only constraints."""
    snapshot = {}
    for root, _, files in os.walk(path):
        for file in files:
            file_path = Path(root) / file
            stat = file_path.stat()
            hasher = hashlib.sha256()
            try:
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        hasher.update(chunk)
                h = hasher.hexdigest()
            except OSError:
                h = "unreadable"
            snapshot[str(file_path.relative_to(path))] = {
                "mtime": stat.st_mtime_ns,
                "size": stat.st_size,
                "hash": h,
            }
    return snapshot


@pytest.fixture
def empty_vault(tmp_path: Path) -> Path:
    config_file = tmp_path / "lifeos.yml"
    config_file.write_text(
        "vault_root: .\nruntime_dir: .lifeos\nfeatures:\n  graphify: true\n  exports: false\n"
    )
    return tmp_path


def run_cli(*args: str) -> tuple[int, str, str]:
    """Run CLI and return exit code, stdout, stderr."""
    stdout_capture = StringIO()
    stderr_capture = StringIO()

    with patch("sys.stdout", stdout_capture), patch("sys.stderr", stderr_capture):
        try:
            code = main(args)
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0

    return code, stdout_capture.getvalue(), stderr_capture.getvalue()


def test_status_help():
    with patch("sys.stdout", StringIO()), patch("sys.stderr", StringIO()):
        with pytest.raises(SystemExit) as exc:
            main(["status", "--help"])
        assert exc.value.code == 0


def test_missing_registry(empty_vault: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(empty_vault)

    # Take a snapshot before
    snapshot_before = snapshot_dir(empty_vault)

    code, out, err = run_cli("status")

    assert code == 0
    assert "Registry" in out
    assert "state: missing" in out

    # Verify no files were created (especially no .lifeos directory or registry.db)
    snapshot_after = snapshot_dir(empty_vault)
    assert snapshot_before == snapshot_after

    # Test JSON mode
    code_json, out_json, err_json = run_cli("status", "--json")
    assert code_json == 0

    data = json.loads(out_json)
    assert data["registry"]["state"] == "missing"
    assert data["registry"]["schema_version"] is None

    # Snapshot should still be identical
    assert snapshot_after == snapshot_dir(empty_vault)


def test_invalid_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    # Write invalid config (no vault_root)
    (tmp_path / "lifeos.yml").write_text("features: {}")

    code, out, err = run_cli("status")
    assert code == 1
    assert "Configuration error" in err

    code_json, out_json, err_json = run_cli("status", "--json")
    assert code_json == 1
    data = json.loads(out_json)
    assert data["error"]["code"] == "config-error"


def test_initialized_populated_vault(empty_vault: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(empty_vault)

    # 1. Create some valid and invalid markdown
    valid_md = empty_vault / "valid.md"
    valid_md.write_text("---\nstatus: active\nconfidence: high\n---\nHello")

    invalid_md = empty_vault / "invalid.md"
    invalid_md.write_text("---\nbad_yaml: [\n---\n")  # Generates frontmatter-invalid-yaml error

    # 2. Initialize registry and insert file counts manually to simulate a scan
    lifeos_dir = empty_vault / ".lifeos"
    registry = Registry(lifeos_dir / "registry.db")
    registry.initialize()

    with registry.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO files (vault_path, file_kind, content_hash, size_bytes, mtime_ns, first_seen_at, last_seen_at, is_deleted)
            VALUES
            ('valid.md', 'markdown', 'hash1', 10, 10, 'now', 'now', 0),
            ('invalid.md', 'markdown', 'hash2', 10, 10, 'now', 'now', 0),
            ('deleted.md', 'markdown', 'hash3', 10, 10, 'now', 'now', 1)
            """
        )
        conn.execute("COMMIT")

    # Take read-only snapshot
    snapshot_before = snapshot_dir(empty_vault)

    code, out, err = run_cli("status")
    assert code == 0

    # Assert human readable
    assert "state: initialized" in out
    assert "active: 2" in out
    assert "deleted: 1" in out
    assert "errors: 1" in out  # invalid YAML
    assert "unavailable in read-only status" in out
    assert "Graphify: enabled" in out
    assert "Exports: disabled" in out

    # Assert JSON
    code_json, out_json, err_json = run_cli("status", "--json")
    assert code_json == 0
    data = json.loads(out_json)

    assert data["registry"]["state"] == "initialized"
    assert data["registry"]["schema_version"] > 0
    assert data["files"]["active"] == 2
    assert data["files"]["deleted"] == 1
    assert data["files"]["comparison_available"] is False
    assert data["lint"]["errors"] == 1
    assert data["features"]["graphify"] is True
    assert data["features"]["exports"] is False

    # Assert Read-Only constraints!
    snapshot_after = snapshot_dir(empty_vault)
    assert snapshot_before == snapshot_after

    # Assert Idempotency
    code2, out2, err2 = run_cli("status")
    assert out == out2


def test_uninitialized_registry(empty_vault: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(empty_vault)

    lifeos_dir = empty_vault / ".lifeos"
    lifeos_dir.mkdir()

    # Create an empty db file without tables
    db_file = lifeos_dir / "registry.db"
    db_file.touch()

    code, out, err = run_cli("status", "--json")
    assert code == 0
    data = json.loads(out)

    assert data["registry"]["state"] == "uninitialized"
    assert data["files"] is None


def test_unreadable_registry(empty_vault: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(empty_vault)

    lifeos_dir = empty_vault / ".lifeos"
    lifeos_dir.mkdir()

    db_file = lifeos_dir / "registry.db"
    db_file.write_bytes(b"not a sqlite db")

    code, out, err = run_cli("status", "--json")
    assert code == 0
    data = json.loads(out)

    assert data["registry"]["state"] == "unreadable"


def test_missing_optional_manifest(empty_vault: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(empty_vault)

    lifeos_dir = empty_vault / ".lifeos"
    lifeos_dir.mkdir()
    registry = Registry(lifeos_dir / "registry.db")
    registry.initialize()

    # Create valid markdown file to ensure lint succeeds
    (empty_vault / "valid.md").write_text("Hello")

    # Do not create ownership.json
    snapshot_before = snapshot_dir(empty_vault)

    code, out, err = run_cli("status", "--json")
    assert code == 0
    data = json.loads(out)

    assert data["lint"]["errors"] == 0

    # Verify manifest wasn't created
    snapshot_after = snapshot_dir(empty_vault)
    assert snapshot_before == snapshot_after


def test_unsupported_registry(empty_vault: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(empty_vault)

    lifeos_dir = empty_vault / ".lifeos"
    lifeos_dir.mkdir()
    registry = Registry(lifeos_dir / "registry.db")
    registry.initialize()

    # Manually insert a future schema version
    with registry.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO schema_migrations (version, name, applied_at)
            VALUES (9999, 'future_schema', 'now')
            """
        )
        conn.execute("COMMIT")

    code, out, err = run_cli("status", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["registry"]["state"] == "unsupported"


def test_status_includes_proposal_counts_with_zeros(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(empty_vault)
    lifeos_dir = empty_vault / ".lifeos"
    registry = Registry(lifeos_dir / "registry.db")
    registry.initialize()

    with registry.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO proposals (id, status, title, created_at, updated_at)
            VALUES
            ('p1', 'draft', 'T1', '2026-01-01', '2026-01-01'),
            ('p2', 'approved', 'T2', '2026-01-01', '2026-01-01'),
            ('p3', 'approved', 'T3', '2026-01-01', '2026-01-01')
            """
        )
        conn.execute("COMMIT")

    code, out, err = run_cli("status")
    assert code == 0
    assert (
        "Proposals\n  draft: 1\n  pending: 0\n  approved: 2\n  rejected: 0\n  applied: 0\n" in out
    )

    code_json, out_json, err_json = run_cli("status", "--json")
    assert code_json == 0
    data = json.loads(out_json)
    assert data["proposals"]["draft"] == 1
    assert data["proposals"]["pending"] == 0
    assert data["proposals"]["approved"] == 2
    assert data["proposals"]["rejected"] == 0
    assert data["proposals"]["applied"] == 0


def test_status_empty_proposals_table_produces_all_zeros(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(empty_vault)
    lifeos_dir = empty_vault / ".lifeos"
    registry = Registry(lifeos_dir / "registry.db")
    registry.initialize()

    code, out, err = run_cli("status")
    assert code == 0
    assert (
        "Proposals\n  draft: 0\n  pending: 0\n  approved: 0\n  rejected: 0\n  applied: 0\n" in out
    )

    code_json, out_json, err_json = run_cli("status", "--json")
    assert code_json == 0
    data = json.loads(out_json)
    assert data["proposals"]["draft"] == 0
    assert data["proposals"]["pending"] == 0
    assert data["proposals"]["approved"] == 0
    assert data["proposals"]["rejected"] == 0
    assert data["proposals"]["applied"] == 0


def test_status_missing_proposals_table_produces_unavailable(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(empty_vault)
    lifeos_dir = empty_vault / ".lifeos"
    db_path = lifeos_dir / "registry.db"

    from lifeos.registry._migrations import MIGRATIONS

    with patch("lifeos.registry._registry._migration_plan", return_value=(MIGRATIONS[0],)):
        Registry(db_path).initialize()

    code, out, err = run_cli("status")
    assert code == 0
    assert "Proposals\n  unavailable\n" in out

    code_json, out_json, err_json = run_cli("status", "--json")
    assert code_json == 0
    data = json.loads(out_json)
    assert data["proposals"] is None


def test_status_corrupted_stored_status_produces_unavailable(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(empty_vault)
    lifeos_dir = empty_vault / ".lifeos"
    registry = Registry(lifeos_dir / "registry.db")
    registry.initialize()

    (empty_vault / "valid.md").write_text("Hello")
    with registry.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO proposals (id, status, title, created_at, updated_at)
            VALUES ('p1', 'corrupt', 'T1', '2026-01-01', '2026-01-01')
            """
        )
        conn.execute(
            """
            INSERT INTO files (vault_path, file_kind, content_hash, size_bytes, mtime_ns, first_seen_at, last_seen_at, is_deleted)
            VALUES ('valid.md', 'markdown', 'hash1', 10, 10, 'now', 'now', 0)
            """
        )
        conn.execute("COMMIT")

    code, out, err = run_cli("status")
    assert code == 0
    assert "Proposals\n  unavailable\n" in out
    assert "active: 1" in out

    code_json, out_json, err_json = run_cli("status", "--json")
    assert code_json == 0
    data = json.loads(out_json)
    assert data["proposals"] is None
    assert data["files"]["active"] == 1


def test_status_no_git_scanner_or_proposal_loader_access(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(empty_vault)
    lifeos_dir = empty_vault / ".lifeos"
    registry = Registry(lifeos_dir / "registry.db")
    registry.initialize()

    with (
        patch(
            "lifeos.registry.proposals.git_tracked_proposal_paths",
            side_effect=Exception("Git accessed!"),
        ),
        patch(
            "lifeos.registry.proposals.load_proposal_directory",
            side_effect=Exception("Files accessed!"),
        ),
        patch(
            "lifeos.registry.file_tracking.register_scan", side_effect=Exception("Scan accessed!")
        ),
        patch(
            "lifeos.registry.proposals.register_proposals_scan",
            side_effect=Exception("Scan accessed!"),
        ),
    ):
        code, out, err = run_cli("status")
        assert code == 0
        assert "Proposals\n  draft: 0" in out


def _check(payload: dict[str, object], subsystem: str) -> dict[str, object]:
    checks = payload["checks"]
    assert isinstance(checks, list)
    return next(item for item in checks if item["subsystem"] == subsystem)


def test_status_expected_lint_unavailability_preserves_other_checks(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(empty_vault)
    from lifeos.scanner import ScannerError

    monkeypatch.setattr(
        "lifeos.status.scan_vault", lambda _root: (_ for _ in ()).throw(ScannerError("no"))
    )

    code, out, err = run_cli("status", "--json")

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert _check(payload, "lint")["state"] == "unavailable"
    assert _check(payload, "configuration")["state"] == "healthy"
    assert _check(payload, "recovery")["state"] == "healthy"


def test_status_programmer_type_error_is_not_swallowed(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(empty_vault)

    def broken_scan(_root: Path) -> list[object]:
        raise TypeError("programmer defect")

    monkeypatch.setattr("lifeos.status.scan_vault", broken_scan)

    with pytest.raises(TypeError, match="programmer defect"):
        main(["status"])


def test_status_json_has_stable_typed_diagnostics(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(empty_vault)

    code, out, err = run_cli("status", "--json")

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    registry = _check(payload, "registry")
    assert registry == {
        "subsystem": "registry",
        "state": "unavailable",
        "code": "registry-missing",
        "detail": "The disposable registry has not been created.",
        "next_action": "Run the registry initialization or rebuild command.",
    }
    assert payload["overall_state"] == "degraded"


def test_status_distinguishes_corrupt_ownership_graph_and_exports(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(empty_vault)
    (empty_vault / "lifeos.yml").write_text(
        "vault_root: .\nruntime_dir: .lifeos\nfeatures:\n  graphify: true\n  exports: true\n"
    )
    manifest = empty_vault / "system" / "generated-ownership.json"
    manifest.parent.mkdir()
    manifest.write_text("not-json", encoding="utf-8")

    from types import SimpleNamespace

    monkeypatch.setattr(
        "lifeos.status.graph_view_status",
        lambda **_kwargs: SimpleNamespace(status="failed"),
    )
    monkeypatch.setattr(
        "lifeos.status.export_status",
        lambda **_kwargs: SimpleNamespace(status="failed"),
    )

    code, out, err = run_cli("status", "--json")

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert _check(payload, "ownership")["code"] == "ownership-invalid"
    assert _check(payload, "graph")["code"] == "graph-publication-corrupt"
    assert _check(payload, "exports")["code"] == "exports-publication-corrupt"


def test_status_blocked_recovery_has_nonzero_exit_and_all_text_names(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(empty_vault)
    from types import SimpleNamespace

    from lifeos.proposals.recovery import RecoveryPhase

    monkeypatch.setattr(
        "lifeos.status.discover_recovery_state",
        lambda **_kwargs: SimpleNamespace(
            journals=(SimpleNamespace(phase=RecoveryPhase.PREPARED),), findings=()
        ),
    )

    code, out, err = run_cli("status")

    assert code == 2
    assert err == ""
    assert "Overall: blocked" in out
    for subsystem in (
        "configuration",
        "registry",
        "files",
        "lint",
        "proposals",
        "ownership",
        "recovery",
        "graph",
        "exports",
    ):
        assert f"  {subsystem}:" in out


def test_status_sanitizes_external_runtime_path(tmp_path: Path) -> None:
    from lifeos.config import FeatureFlags, LifeOSConfig
    from lifeos.status import collect_status, serialize_status_json

    vault = tmp_path / "vault"
    vault.mkdir()
    external = tmp_path / "private-host-path" / "runtime"
    config = LifeOSConfig(vault, external, FeatureFlags())
    result = collect_status(config, Registry(external / "registry.db"))

    payload = json.loads(serialize_status_json(result))
    assert payload["registry"]["database_path"] == "<external-runtime>/registry.db"
    assert str(tmp_path) not in serialize_status_json(result)


def _write_ownership_manifest(manifest_path: Path, entries: dict[str, str]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "owned_files": {
                    path: {
                        "generator_id": "status-test",
                        "generator_version": "1",
                        "content_hash": content_hash,
                        "created_at": "1",
                        "updated_at": "1",
                    }
                    for path, content_hash in entries.items()
                },
            }
        ),
        encoding="utf-8",
    )


def test_status_lint_uses_canonical_ownership_and_is_read_only(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(empty_vault)
    target = empty_vault / "generated.md"
    target.write_text("modified", encoding="utf-8")
    canonical_manifest = empty_vault / "system" / "generated-ownership.json"
    _write_ownership_manifest(
        canonical_manifest,
        {"generated.md": hashlib.sha256(b"original").hexdigest()},
    )
    runtime_manifest = empty_vault / ".lifeos" / "ownership.json"
    _write_ownership_manifest(
        runtime_manifest,
        {"generated.md": hashlib.sha256(b"modified").hexdigest()},
    )
    snapshot_before = snapshot_dir(empty_vault)

    code, out, err = run_cli("status", "--json")

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["lint"]["errors"] == 1
    assert _check(payload, "lint")["code"] == "lint-errors"
    assert _check(payload, "ownership")["code"] == "ownership-valid"
    assert snapshot_dir(empty_vault) == snapshot_before


def test_status_lint_reports_missing_canonical_owned_file(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(empty_vault)
    canonical_manifest = empty_vault / "system" / "generated-ownership.json"
    _write_ownership_manifest(canonical_manifest, {"missing.md": "a" * 64})
    runtime_manifest = empty_vault / ".lifeos" / "ownership.json"
    _write_ownership_manifest(runtime_manifest, {})

    code, out, err = run_cli("status", "--json")

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["lint"]["errors"] == 1
    assert _check(payload, "lint")["code"] == "lint-errors"
    assert _check(payload, "ownership")["code"] == "ownership-valid"


def test_status_lint_ignores_malformed_runtime_manifest_when_canonical_is_absent(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(empty_vault)
    runtime_manifest = empty_vault / ".lifeos" / "ownership.json"
    runtime_manifest.parent.mkdir()
    runtime_manifest.write_text("not-json", encoding="utf-8")

    code, out, err = run_cli("status", "--json")

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["lint"]["errors"] == 0
    assert _check(payload, "lint")["code"] == "lint-clean"
    assert _check(payload, "ownership")["code"] == "ownership-absent"


def test_status_external_runtime_still_uses_canonical_ownership(tmp_path: Path) -> None:
    from lifeos.config import FeatureFlags, LifeOSConfig
    from lifeos.status import collect_status, serialize_status_json

    vault = tmp_path / "vault"
    vault.mkdir()
    target = vault / "generated.md"
    target.write_text("modified", encoding="utf-8")
    _write_ownership_manifest(
        vault / "system" / "generated-ownership.json",
        {"generated.md": hashlib.sha256(b"original").hexdigest()},
    )
    external = tmp_path / "external-runtime"
    _write_ownership_manifest(
        external / "ownership.json",
        {"generated.md": hashlib.sha256(b"modified").hexdigest()},
    )
    config = LifeOSConfig(vault, external, FeatureFlags())

    payload = json.loads(serialize_status_json(collect_status(config, Registry(external / "registry.db"))))

    assert payload["lint"]["errors"] == 1
    assert _check(payload, "lint")["code"] == "lint-errors"
    assert _check(payload, "ownership")["code"] == "ownership-valid"


def test_status_path_safety_failure_preserves_partial_diagnostics(
    empty_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(empty_vault)
    canonical_manifest = empty_vault / "system" / "generated-ownership.json"
    _write_ownership_manifest(canonical_manifest, {})

    from lifeos.ownership import GeneratedOwnership, PathSafetyError

    def unsafe_load(*_args: object, **_kwargs: object) -> None:
        raise PathSafetyError("unsafe canonical ownership path")

    monkeypatch.setattr(GeneratedOwnership, "load_if_present", unsafe_load)

    code, out, err = run_cli("status", "--json")

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["lint"] is None
    assert _check(payload, "lint")["code"] == "lint-unavailable"
    assert _check(payload, "ownership")["code"] == "ownership-unsafe-path"
