from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import lifeos.captures.recovery as capture_recovery
from lifeos.captures.artifact import CaptureArtifactService

NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)


def test_interrupted_capture_recovery_reads_only_the_bounded_source_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    captures = CaptureArtifactService(vault_root=vault, runtime_dir=runtime)
    for index in range(3):
        captures.create(
            title=f"Capture {index}",
            capture_type="meal",
            now=NOW + timedelta(seconds=index),
        )

    reads: list[str] = []
    real_read = capture_recovery.read_vault_markdown

    def recording_read(vault_root: Path, relative_path: str):
        reads.append(relative_path)
        return real_read(vault_root, relative_path)

    def unexpected_full_audit(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("full capture audit ran after an interrupted rebuild")

    monkeypatch.setattr(capture_recovery, "read_vault_markdown", recording_read)
    monkeypatch.setattr(CaptureArtifactService, "list", unexpected_full_audit)

    report = capture_recovery.audit_capture_recovery(
        vault_root=vault,
        runtime_dir=runtime,
        rebuild=True,
        batch_size=1,
        interrupt_after=1,
    )

    assert report.state == "interrupted"
    assert report.index.state == "interrupted"
    assert len(reads) == 1
    assert reads[0].startswith("captures/")
    assert report.rebuilt_manifests == ()
