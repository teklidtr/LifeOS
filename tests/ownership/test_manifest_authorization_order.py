import os
from pathlib import Path

import pytest

import lifeos.ownership.manifest as ownership_manifest
from lifeos.ownership import GeneratorMismatchError, GeneratedOwnership, UnownedFileError


def _vault(tmp_path: Path) -> Path:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    return vault_root


def _forbid_content_observation(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("unauthorized target contents must not be observed")


def test_unowned_target_is_rejected_before_content_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    ownership = GeneratedOwnership.load(tmp_path / "manifest.json", vault_root)
    target = vault_root / "human.md"
    target.write_bytes(b"private human content")

    monkeypatch.setattr(
        ownership_manifest,
        "observe_vault_file",
        _forbid_content_observation,
    )

    with pytest.raises(UnownedFileError, match="exists but is unowned"):
        ownership.write_generated_file("human.md", b"generated", "gen", "1")

    assert target.read_bytes() == b"private human content"


def test_generator_mismatch_is_rejected_before_content_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    ownership = GeneratedOwnership.load(tmp_path / "manifest.json", vault_root)
    ownership.write_generated_file("owned.md", b"v1", "gen-a", "1")
    original_entry = ownership.entries["owned.md"]

    monkeypatch.setattr(
        ownership_manifest,
        "observe_vault_file",
        _forbid_content_observation,
    )

    with pytest.raises(GeneratorMismatchError, match="owned by gen-a, not gen-b"):
        ownership.write_generated_file("owned.md", b"v2", "gen-b", "2")

    assert (vault_root / "owned.md").read_bytes() == b"v1"
    assert ownership.entries["owned.md"] == original_entry


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_unowned_fifo_preserves_unowned_error_without_content_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    ownership = GeneratedOwnership.load(tmp_path / "manifest.json", vault_root)
    target = vault_root / "human.pipe"
    os.mkfifo(target)

    monkeypatch.setattr(
        ownership_manifest,
        "observe_vault_file",
        _forbid_content_observation,
    )

    with pytest.raises(UnownedFileError, match="exists but is unowned"):
        ownership.write_generated_file("human.pipe", b"generated", "gen", "1")
