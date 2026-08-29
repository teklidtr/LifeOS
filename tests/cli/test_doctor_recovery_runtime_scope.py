from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from lifeos.config import load_config
from lifeos.entrypoint import main
from lifeos.recovery_readiness import collect_recovery_readiness


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )


def _commit_all(repository: Path, message: str) -> None:
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


def test_recovery_reuses_filesystem_aware_runtime_exclusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "lifeos.yml").write_text(
        "vault_root: .\nruntime_dir: runtime/node-a\n",
        encoding="utf-8",
    )
    _commit_all(vault, "canonical baseline")

    case_variant_runtime = vault / "Runtime" / "node-a" / "cache.bin"
    case_variant_runtime.parent.mkdir(parents=True)
    case_variant_runtime.write_bytes(b"derived")

    observed: list[dict[str, object]] = []

    def fake_build_runtime_exclusion_matcher(
        vault_root: Path,
        *,
        runtime_dir: Path | None,
        snapshot_prefix: str | None,
    ) -> Callable[[str], bool]:
        observed.append(
            {
                "vault_root": vault_root,
                "runtime_dir": runtime_dir,
                "snapshot_prefix": snapshot_prefix,
            }
        )
        return lambda path: path.startswith("Runtime/node-a/")

    monkeypatch.setattr(
        "lifeos.recovery_readiness.build_runtime_exclusion_matcher",
        fake_build_runtime_exclusion_matcher,
    )

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))

    assert {
        "vault_root": vault.resolve(),
        "runtime_dir": (vault / "runtime" / "node-a").resolve(strict=False),
        "snapshot_prefix": "runtime/node-a/",
    } in observed
    assert report.untracked_paths == ()
    assert all("Runtime/node-a" not in path for path in report.uncommitted_paths)
