from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lifeos.cli import main
from lifeos.config import FeatureFlags, LifeOSConfig
from lifeos.exports import build_export, export_status
from lifeos.registry import Registry
from lifeos.status import collect_status


def _write(vault: Path, relative: str, content: str) -> Path:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _build_public(vault: Path, runtime: Path) -> None:
    build_export(vault_root=vault, runtime_dir=runtime, kind="public-wiki")


def _snapshot(path: Path) -> dict[str, tuple[int, int]]:
    if not path.exists():
        return {}
    snapshot: dict[str, tuple[int, int]] = {}
    for root, _directories, files in os.walk(path):
        for name in files:
            item = Path(root) / name
            stat = item.stat()
            snapshot[item.relative_to(path).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def test_editing_included_note_marks_export_stale_and_rebuild_restores_ready(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    note = _write(vault, "wiki/note.md", "Old.\n")
    _build_public(vault, runtime)
    assert (
        export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki").status == "ready"
    )

    note.write_text("New.\n", encoding="utf-8")
    assert (
        export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki").status == "stale"
    )

    _build_public(vault, runtime)
    assert (
        export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki").status == "ready"
    )


@pytest.mark.parametrize("change", ["add", "delete"])
def test_included_note_inventory_changes_mark_export_stale(tmp_path: Path, change: str) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    first = _write(vault, "wiki/first.md", "First.\n")
    _build_public(vault, runtime)

    if change == "add":
        _write(vault, "wiki/second.md", "Second.\n")
    else:
        first.unlink()

    assert (
        export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki").status == "stale"
    )


def test_visibility_and_archived_inclusion_changes_mark_export_stale(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    note = _write(
        vault,
        "wiki/note.md",
        "---\nvisibility: public\nstatus: active\n---\nVisible.\n",
    )
    _build_public(vault, runtime)

    note.write_text(
        "---\nvisibility: private\nstatus: active\n---\nVisible.\n",
        encoding="utf-8",
    )
    assert (
        export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki").status == "stale"
    )

    note.write_text(
        "---\nvisibility: public\nstatus: active\n---\nVisible.\n",
        encoding="utf-8",
    )
    _build_public(vault, runtime)
    note.write_text(
        "---\nvisibility: public\nstatus: archived\n---\nVisible.\n",
        encoding="utf-8",
    )
    assert (
        export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki").status == "stale"
    )


def test_unrelated_journal_change_does_not_stale_public_wiki(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    _write(vault, "wiki/note.md", "Wiki.\n")
    journal = _write(vault, "journal/day.md", "Morning.\n")
    _build_public(vault, runtime)

    journal.write_text("Evening.\n", encoding="utf-8")

    assert (
        export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki").status == "ready"
    )


def test_malformed_selected_source_returns_typed_failed_diagnostic(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    note = _write(vault, "wiki/note.md", "Valid.\n")
    _build_public(vault, runtime)
    note.write_text("---\nbroken: [\n---\n", encoding="utf-8")

    state = export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki")

    assert state.status == "failed"
    assert len(state.diagnostics) == 1
    assert state.diagnostics[0].source_path == "wiki/note.md"
    assert state.diagnostics[0].code == "frontmatter-invalid-yaml"


def test_export_status_cli_text_and_json_agree_on_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    note = _write(vault, "wiki/note.md", "Old.\n")
    (tmp_path / "lifeos.yml").write_text(
        f"vault_root: {vault}\nfeatures:\n  exports: true\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["export", "build", "public-wiki"]) == 0
    capsys.readouterr()
    note.write_text("New.\n", encoding="utf-8")

    assert main(["export", "status", "public-wiki"]) == 0
    text = capsys.readouterr()
    assert "Export public-wiki: stale" in text.out

    assert main(["export", "status", "public-wiki", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "stale"


def test_top_level_status_reports_stale_exports_without_mutation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    note = _write(vault, "wiki/note.md", "Old.\n")
    _build_public(vault, runtime)
    note.write_text("New.\n", encoding="utf-8")
    registry = Registry(runtime / "registry.db")
    registry.initialize()
    config = LifeOSConfig(vault, runtime, FeatureFlags(graphify=False, exports=True))
    before_vault = _snapshot(vault)
    before_runtime = _snapshot(runtime)

    result = collect_status(config, registry)

    export_check = next(check for check in result.checks if check.subsystem == "exports")
    assert export_check.state == "stale"
    assert export_check.code == "exports-stale"
    assert _snapshot(vault) == before_vault
    assert _snapshot(runtime) == before_runtime
