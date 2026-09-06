from __future__ import annotations

import importlib
import json
import os
import stat
import subprocess
import types
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest

import lifeos.recovery_readiness as recovery_readiness
from lifeos.config import load_config
from lifeos.entrypoint import main
from lifeos.recovery_readiness import collect_recovery_readiness, recovery_report_to_dict
from lifeos.retrieval.contracts import RetrievalPolicy, RetrievalScope
from lifeos.runtime_scope import build_runtime_exclusion_matcher


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )


def _commit_all(repository: Path, message: str) -> str:
    _git(repository, "add", "-A")
    _git(
        repository,
        "-c",
        "user.name=LifeOS Test",
        "-c",
        "user.email=lifeos@example.invalid",
        "commit",
        "-q",
        "-m",
        message,
    )
    return _git(repository, "rev-parse", "HEAD").stdout.strip()


def _diagnostics(
    report: recovery_readiness.RecoveryReport,
) -> dict[str, recovery_readiness.RecoveryDiagnostic]:
    return {item.id: item for item in report.diagnostics}


def test_git_metadata_sandbox_ignores_repository_include_added_after_snapshot(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "note.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(vault, "baseline")

    sandbox = recovery_readiness._build_sandbox(vault)
    assert sandbox is not None
    token = recovery_readiness._ACTIVE_SANDBOX.set(sandbox)
    try:
        protected = vault / "secrets" / "invalid.conf"
        protected.parent.mkdir()
        protected.write_text("[broken\n", encoding="utf-8")
        with (vault / ".git" / "config").open("a", encoding="utf-8") as handle:
            handle.write("\n[include]\n\tpath = ../secrets/invalid.conf\n")

        result = recovery_readiness._run_git(
            recovery_readiness._resolve_git_executable(),
            cwd=vault,
            arguments=("rev-parse", "--show-toplevel"),
            check=False,
        )

        assert result.returncode == 0
        assert result.stderr == b""
        assert result.stdout.decode().rstrip("\n") == str(vault.resolve())
    finally:
        recovery_readiness._ACTIVE_SANDBOX.reset(token)
        sandbox.close()


def test_positive_nested_vault_pathspec_uses_icase_when_filesystem_requires_it() -> None:
    context = SimpleNamespace(prefix=("vault",), case_insensitive_prefix=True)
    scope = recovery_readiness._ScopeFilter(
        lambda _path: False,
        RetrievalPolicy(protected_prefixes=()),
        RetrievalScope(),
        case_insensitive=True,
    )
    config = SimpleNamespace(vault_root=Path("/vault"), runtime_dir=Path("/vault/.lifeos"))

    pathspecs = recovery_readiness._authorized_git_pathspecs(context, scope, config)

    assert pathspecs[0] == ":(top,icase,literal)vault"


def test_case_sensitive_policy_does_not_hide_distinct_case_path() -> None:
    scope = recovery_readiness._ScopeFilter(
        lambda _path: False,
        RetrievalPolicy(),
        RetrievalScope(),
        case_insensitive=False,
    )

    assert scope("Private/note.md") is False
    assert scope.incomplete is False
    assert scope("private/note.md") is True
    assert scope.incomplete is True


def test_unicode_normalized_filesystem_spelling_reconciles_by_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nfc = "wiki/caf\N{LATIN SMALL LETTER E WITH ACUTE}.md"
    nfd = unicodedata.normalize("NFD", nfc)
    observed = SimpleNamespace(st_dev=17, st_ino=19)
    snapshot = recovery_readiness._WorkingTreeSnapshot(
        (
            recovery_readiness._FsEntry(
                nfd,
                stat.S_IFREG | 0o644,
                7,
                11,
                13,
                observed.st_dev,
                observed.st_ino,
            ),
        )
    )
    monkeypatch.setattr(recovery_readiness, "_lstat", lambda _vault, _path: observed)

    matched = recovery_readiness._snapshot_entry_for_index_path(tmp_path, nfc, snapshot)

    assert matched is not None
    assert matched.path == nfd


def test_racily_clean_index_entry_is_metadata_uncertain(tmp_path: Path) -> None:
    entry = recovery_readiness._IndexEntry(
        "wiki/note.md",
        0o100644,
        "0" * 40,
        100,
        200,
        17,
        19,
        7,
    )
    observed = recovery_readiness._FsEntry(
        "wiki/note.md",
        stat.S_IFREG | 0o644,
        7,
        200,
        100,
        17,
        19,
    )
    temporary = recovery_readiness.tempfile.TemporaryDirectory(prefix="lifeos-racy-test-")
    sandbox = recovery_readiness._GitMetadataSandbox(
        temporary,
        tmp_path,
        tmp_path,
        tmp_path,
        tmp_path,
        200,
        "fingerprint",
        False,
        False,
    )
    token = recovery_readiness._ACTIVE_SANDBOX.set(sandbox)
    try:
        assert recovery_readiness._compare_index_entry(entry, observed) == "uncertain"
    finally:
        recovery_readiness._ACTIVE_SANDBOX.reset(token)
        sandbox.close()


def test_deleted_protected_history_marks_latest_commit_evidence_incomplete(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "system" / "retrieval-policy.yml").write_text(
        "schema_version: 1\nprotected_prefixes:\n  - secrets\n",
        encoding="utf-8",
    )
    (vault / "wiki" / "visible.md").write_text("visible\n", encoding="utf-8")
    protected = vault / "secrets" / "private.md"
    protected.parent.mkdir()
    protected.write_text("private\n", encoding="utf-8")
    _commit_all(vault, "with protected history")
    protected.unlink()
    protected.parent.rmdir()
    _commit_all(vault, "delete protected history")

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    rendered = json.dumps(recovery_report_to_dict(report), ensure_ascii=True)
    diagnostics = _diagnostics(report)

    assert "secrets/private.md" not in rendered
    assert diagnostics["recovery.git.last_canonical_commit"].status == "unknown"
    assert (
        "protected or policy-excluded" in diagnostics["recovery.git.last_canonical_commit"].summary
    )


def test_runtime_scope_preserves_configured_whitespace_component(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / " runtime "
    runtime.mkdir(parents=True)
    matcher = build_runtime_exclusion_matcher(
        vault,
        runtime_dir=runtime,
        snapshot_prefix=" runtime /",
    )

    assert matcher(" runtime /registry.db") is True
    assert matcher("runtime/registry.db") is False
    assert matcher(" runtime/registry.db") is False


def test_config_snapshot_ignores_core_subsection_and_preserves_ignorecase(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.write_text(
        "[core]\n"
        "\tfilemode = false\n"
        "\tignorecase = true\n"
        '[core "doctor"]\n'
        "\tfilemode = true\n"
        "\trepositoryformatversion = 1\n",
        encoding="utf-8",
    )

    _raw, includes, filemode, ignorecase = recovery_readiness._config_snapshot(config)

    assert includes is False
    assert filemode is False
    assert ignorecase is True


def test_git_metadata_hardlink_is_rejected_before_read(tmp_path: Path) -> None:
    config = tmp_path / "config"
    alias = tmp_path / "protected-note.md"
    config.write_text("[core]\n\tfilemode = true\n", encoding="utf-8")
    os.link(config, alias)

    with pytest.raises(recovery_readiness.RecoveryGitError, match="hard link"):
        recovery_readiness._read_small_metadata(config)


def test_metadata_fingerprint_tracks_repository_exclude_file(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    (git_dir / "objects").mkdir(parents=True)
    (git_dir / "refs").mkdir()
    (git_dir / "info").mkdir()
    exclude = git_dir / "info" / "exclude"
    exclude.write_text("first\n", encoding="utf-8")

    before = recovery_readiness._metadata_fingerprint(git_dir)
    exclude.write_text("second\n", encoding="utf-8")
    after = recovery_readiness._metadata_fingerprint(git_dir)

    assert before != after


def test_split_index_topology_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    git_dir = vault / ".git"
    (git_dir / "objects").mkdir(parents=True)
    (git_dir / "refs").mkdir()
    (git_dir / "sharedindex.test").write_bytes(b"shared")

    with pytest.raises(recovery_readiness.RecoveryGitError, match="Split-index"):
        recovery_readiness._build_sandbox(vault)


def test_redirected_object_store_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    git_dir = vault / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "refs").mkdir()
    external = tmp_path / "objects"
    external.mkdir()
    (git_dir / "objects").symlink_to(external, target_is_directory=True)

    with pytest.raises(recovery_readiness.RecoveryGitError, match="Redirected"):
        recovery_readiness._build_sandbox(vault)


def test_alternate_object_store_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    git_dir = vault / ".git"
    alternates = git_dir / "objects" / "info" / "alternates"
    alternates.parent.mkdir(parents=True)
    alternates.write_text("/elsewhere\n", encoding="utf-8")
    (git_dir / "refs").mkdir()

    with pytest.raises(recovery_readiness.RecoveryGitError, match="Alternate"):
        recovery_readiness._build_sandbox(vault)


def test_normalization_sensitive_denied_prefix_fails_before_git_pathspec() -> None:
    context = SimpleNamespace(prefix=(), case_insensitive_prefix=False)
    scope = recovery_readiness._ScopeFilter(
        lambda _path: False,
        RetrievalPolicy(protected_prefixes=("s\N{LATIN SMALL LETTER E WITH ACUTE}crets",)),
        RetrievalScope(),
    )
    config = SimpleNamespace(vault_root=Path("/vault"), runtime_dir=Path("/vault/.lifeos"))

    with pytest.raises(recovery_readiness.RecoveryGitError, match="normalization"):
        recovery_readiness._authorized_git_pathspecs(context, scope, config)


def test_repository_metadata_case_alias_is_excluded_by_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = tmp_path / ".git"
    metadata.mkdir()
    metadata_fd = recovery_readiness._open_metadata_directory(metadata)
    assert metadata_fd is not None
    temporary = recovery_readiness.tempfile.TemporaryDirectory(prefix="lifeos-git-alias-test-")
    sandbox = recovery_readiness._GitMetadataSandbox(
        temporary,
        tmp_path,
        tmp_path,
        tmp_path,
        tmp_path,
        None,
        "fingerprint",
        False,
        False,
        metadata_fd=metadata_fd,
    )
    state = os.fstat(metadata_fd)
    real_stat = recovery_readiness.os.stat

    def fake_stat(path: object, *args: object, **kwargs: object) -> object:
        spelling = os.fspath(path)
        if spelling.endswith("/.GIT"):
            return state
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(recovery_readiness.os, "stat", fake_stat)
    token = recovery_readiness._ACTIVE_SANDBOX.set(sandbox)
    try:
        scope = recovery_readiness._ScopeFilter(
            lambda _path: False,
            RetrievalPolicy(protected_prefixes=()),
            RetrievalScope(),
        )
        assert scope(".GIT/objects/aa") is True
        assert scope.incomplete is False
    finally:
        recovery_readiness._ACTIVE_SANDBOX.reset(token)
        sandbox.close()


def test_ambiguous_policy_prefix_fails_before_worktree_scan(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "system" / "retrieval-policy.yml").write_text(
        'schema_version: 1\nprotected_prefixes:\n  - " private"\n',
        encoding="utf-8",
    )
    protected = vault / " private" / "secret.md"
    protected.parent.mkdir()
    protected.write_text("secret\n", encoding="utf-8")

    def fail_scan(_vault: Path, _excluded: object) -> object:
        raise AssertionError("canonical worktree scanning must not start")

    monkeypatch.setattr(recovery_readiness, "_scan_working_tree_snapshot", fail_scan)
    report = recovery_readiness.collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostics = _diagnostics(report)
    rendered = json.dumps(recovery_report_to_dict(report), ensure_ascii=True)

    assert diagnostics["recovery.git.repository"].status == "unknown"
    assert "unambiguous literal POSIX spelling" in diagnostics["recovery.git.repository"].summary
    assert " private/secret.md" not in rendered


def test_hidden_probes_ignore_runtime_inside_protected_scope(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")
    runtime = repository / "private" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "cache.md").write_text("runtime\n", encoding="utf-8")
    wiki = repository / "wiki"
    wiki.mkdir()
    (wiki / "note.md").write_text("visible\n", encoding="utf-8")
    baseline = _commit_all(repository, "baseline")

    config = SimpleNamespace(vault_root=repository, runtime_dir=runtime)
    context = SimpleNamespace(prefix=(), case_insensitive_prefix=False)
    scope = recovery_readiness._ScopeFilter(
        lambda path: path == "private/runtime" or path.startswith("private/runtime/"),
        RetrievalPolicy(protected_prefixes=("private",)),
        RetrievalScope(),
    )
    git = recovery_readiness._resolve_git_executable()
    assert git is not None
    config_token = recovery_readiness._ACTIVE_CONFIG.set(config)
    try:
        assert recovery_readiness._hidden_index_state(git, repository, context, scope) == (False,)
        pathspec = recovery_readiness._authorized_git_pathspecs(context, scope, config)
        visible = recovery_readiness._latest_commit(
            git,
            repository,
            pathspec,
            (),
            scope,
            recovery_readiness._utc_now,
            head_oid=baseline,
        )
        assert visible is not None
        assert scope.incomplete is False

        protected = repository / "private" / "secret.md"
        protected.write_text("protected\n", encoding="utf-8")
        _git(repository, "add", "private/secret.md")
        assert recovery_readiness._hidden_index_state(git, repository, context, scope) == (True,)
        protected_head = _commit_all(repository, "protected sibling")
        scope.incomplete = False
        hidden = recovery_readiness._latest_commit(
            git,
            repository,
            pathspec,
            (),
            scope,
            recovery_readiness._utc_now,
            head_oid=protected_head,
        )
        assert hidden is None
        assert scope.incomplete is True
    finally:
        recovery_readiness._ACTIVE_CONFIG.reset(config_token)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_untracked_symlink_is_structural_recovery_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "note.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(vault, "baseline")
    outside = tmp_path / "outside.md"
    outside.write_text("outside body\n", encoding="utf-8")
    link = vault / "wiki" / "linked.md"
    link.symlink_to(outside)

    report = recovery_readiness.collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostics = _diagnostics(report)

    assert "wiki/linked.md" in report.untracked_paths
    objects = diagnostics["recovery.git.canonical_objects"]
    assert objects.status == "failure"
    assert objects.severity == "error"
    assert objects.paths == ("wiki/linked.md",)
    assert objects.remediation is not None and "symlink" in objects.remediation
    untracked = diagnostics["recovery.git.untracked_canonical"]
    assert untracked.remediation is not None and "non-regular" in untracked.remediation


def test_recovery_module_reload_preserves_latest_commit_behavior(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "note.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(vault, "baseline")

    reloaded = importlib.reload(recovery_readiness)
    report = reloaded.collect_recovery_readiness(load_config(vault / "lifeos.yml"))

    assert type(reloaded) is types.ModuleType
    assert report.last_canonical_commit is not None
