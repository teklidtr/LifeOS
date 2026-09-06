from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.entrypoint import main


def _note(stable_id: str) -> str:
    return f"---\nid: {stable_id}\ntype: wiki\ntitle: Example\n---\nBody\n"


def test_doctor_exposes_single_writer_and_node_local_state_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    real_which = __import__("shutil").which
    monkeypatch.setattr(
        "lifeos.doctor.shutil.which",
        lambda name: None if name == "lifeos-mcp" else real_which(name),
    )

    assert main(["doctor", "--config", str(vault / "lifeos.yml"), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    topology = payload["coherence"]["topology"]
    assert topology["writer_model"] == "single-active-lifeos-writer"
    assert topology["sync_transport_owner"] == "external"
    assert topology["runtime_location"] == "inside-canonical-vault"
    assert ".lifeos/" in topology["required_sync_exclusions"]
    assert any(
        finding["code"] == "runtime-state-sync-exclusion-required" and finding["state"] == "warning"
        for finding in payload["findings"]
    )


def test_doctor_blocks_ambiguous_stable_note_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "a.md").write_text(_note("duplicate"), encoding="utf-8")
    (vault / "wiki" / "b.md").write_text(_note("duplicate"), encoding="utf-8")
    real_which = __import__("shutil").which
    monkeypatch.setattr(
        "lifeos.doctor.shutil.which",
        lambda name: None if name == "lifeos-mcp" else real_which(name),
    )

    exit_code = main(["doctor", "--config", str(vault / "lifeos.yml"), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ready"] is False
    assert any(
        finding["code"] == "stable-id-ambiguous" and finding["state"] == "blocked"
        for finding in payload["findings"]
    )


def test_doctor_excludes_custom_in_vault_runtime_from_identity_diagnostics(
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
    canonical = vault / "wiki" / "note.md"
    runtime_copy = vault / "runtime" / "node-a" / "exports" / "wiki" / "note.md"
    canonical.write_text(_note("shared-id"), encoding="utf-8")
    runtime_copy.parent.mkdir(parents=True)
    runtime_copy.write_text(_note("shared-id"), encoding="utf-8")
    real_which = __import__("shutil").which
    monkeypatch.setattr(
        "lifeos.doctor.shutil.which",
        lambda name: None if name == "lifeos-mcp" else real_which(name),
    )

    exit_code = main(["doctor", "--config", str(vault / "lifeos.yml"), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["coherence"]["identity_note_count"] == 1
    assert payload["coherence"]["relocation_safe_note_count"] == 1
    assert not any(finding["code"] == "stable-id-ambiguous" for finding in payload["findings"])
