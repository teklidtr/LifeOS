from __future__ import annotations

from pathlib import Path

import pytest

from lifeos.bootstrap import VAULT_ROOTS
from lifeos.config import load_config
from lifeos.entrypoint import main


def test_init_creates_valid_vault_and_rerun_is_non_destructive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "LifeOS-vault"

    exit_code = main(["init", str(vault)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Initialized LifeOS vault" in captured.out
    assert captured.err == ""
    for name in VAULT_ROOTS:
        assert (vault / name).is_dir()
    assert (vault / ".git").is_dir()
    assert (vault / ".gitignore").is_file()
    assert (vault / "AGENTS.md").is_file()
    assert (vault / "system/instructions.yml").is_file()
    assert (vault / "system/generated-ownership.json").is_file()

    config = load_config(vault / "lifeos.yml")
    assert config.vault_root == vault.resolve()
    assert config.runtime_dir == (vault / ".lifeos").resolve()

    customized = "schema_version: 1\ninstructions:\n  - id: custom\n    text: Keep this.\n"
    instructions = vault / "system/instructions.yml"
    instructions.write_text(customized, encoding="utf-8")

    rerun_code = main(["init", str(vault)])

    rerun = capsys.readouterr()
    assert rerun_code == 0
    assert "already initialized" in rerun.out
    assert rerun.err == ""
    assert instructions.read_text(encoding="utf-8") == customized


def test_init_rejects_non_empty_non_lifeos_directory_without_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("do not touch\n", encoding="utf-8")

    exit_code = main(["init", str(target)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Refusing to initialize non-empty directory" in captured.err
    assert marker.read_text(encoding="utf-8") == "do not touch\n"
    assert not (target / "lifeos.yml").exists()
    assert not (target / ".git").exists()


def test_init_rejects_partial_lifeos_scaffold_instead_of_repairing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "partial"
    target.mkdir()
    (target / "system").mkdir()
    instructions = target / "system/instructions.yml"
    instructions.write_text("schema_version: 1\ninstructions: []\n", encoding="utf-8")

    exit_code = main(["init", str(target)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Refusing to initialize non-empty directory" in captured.err
    assert instructions.read_text(encoding="utf-8") == "schema_version: 1\ninstructions: []\n"
    assert not (target / "lifeos.yml").exists()


def test_init_without_path_uses_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "current-vault"
    vault.mkdir()
    monkeypatch.chdir(vault)

    exit_code = main(["init"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert (vault / "lifeos.yml").is_file()
    assert load_config(vault / "lifeos.yml").vault_root == vault.resolve()
