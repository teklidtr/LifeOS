from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.exports import ExportError, build_export


def _write(vault: Path, relative: str, content: str) -> None:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_public_wiki_excludes_private_and_archived_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    _write(vault, "wiki/public.md", "---\ntitle: Public\n---\nSee [[wiki/other|Other]].\n")
    _write(vault, "wiki/other.md", "---\ntitle: Other\n---\n")
    _write(vault, "wiki/private.md", "---\nvisibility: private\n---\nSecret.\n")
    _write(vault, "wiki/old.md", "---\nstatus: archived\n---\nOld.\n")

    result = build_export(vault_root=vault, runtime_dir=runtime, kind="public-wiki")

    output = runtime / result.output_dir
    assert result.file_count == 2
    assert (output / "wiki" / "public.md").exists()
    assert not (output / "wiki" / "private.md").exists()
    assert not (output / "wiki" / "old.md").exists()
    assert "[Other](other.md)" in (output / "wiki" / "public.md").read_text()


def test_export_manifest_records_hashes_and_is_deterministic(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    _write(vault, "study/chapter.md", "Study text.\n")
    _write(vault, "flashcards/card.md", "Card text.\n")

    first = build_export(vault_root=vault, runtime_dir=runtime, kind="study-bundle")
    first_manifest = (runtime / first.output_dir / "manifest.json").read_bytes()
    second = build_export(vault_root=vault, runtime_dir=runtime, kind="study-bundle")
    second_manifest = (runtime / second.output_dir / "manifest.json").read_bytes()

    assert first.source_hash == second.source_hash
    assert first_manifest == second_manifest
    manifest = json.loads(first_manifest)
    assert manifest["schema_version"] == 2
    assert manifest["rendering_policy_version"] == "portable-wikilinks-v2"
    assert manifest["file_count"] == 2
    assert all(len(item["source_hash"]) == 64 for item in manifest["files"])
    assert all(len(item["rendered_hash"]) == 64 for item in manifest["files"])


def test_exports_are_purpose_specific(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    _write(vault, "journal/day.md", "Journal.\n")
    _write(vault, "wiki/concept.md", "Concept.\n")
    _write(vault, "system/policy.md", "Policy.\n")

    personal = build_export(vault_root=vault, runtime_dir=runtime, kind="personal-review")
    trusted = build_export(vault_root=vault, runtime_dir=runtime, kind="trusted-agent")

    personal_root = runtime / personal.output_dir
    trusted_root = runtime / trusted.output_dir
    assert (personal_root / "journal" / "day.md").exists()
    assert not (personal_root / "system" / "policy.md").exists()
    assert (trusted_root / "system" / "policy.md").exists()
    assert not (trusted_root / "journal" / "day.md").exists()


def test_invalid_export_kind_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ExportError, match="kind"):
        build_export(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", kind="mirror")


def test_public_wiki_privacy_markers_are_case_insensitive(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    _write(vault, "wiki/private.md", "---\nvisibility: ' Private '\n---\nSecret.\n")
    _write(vault, "wiki/archived.md", "---\nstatus: ARCHIVED\n---\nOld.\n")
    _write(vault, "wiki/public.md", "---\nvisibility: public\n---\nShareable.\n")

    result = build_export(vault_root=vault, runtime_dir=runtime, kind="public-wiki")

    output = runtime / result.output_dir / "wiki"
    assert result.file_count == 1
    assert (output / "public.md").exists()
    assert not (output / "private.md").exists()
    assert not (output / "archived.md").exists()


def test_public_wiki_rejects_malformed_visibility_metadata(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    _write(
        vault,
        "wiki/ambiguous.md",
        "---\nvisibility:\n  - private\n---\nPotential secret.\n",
    )

    with pytest.raises(ExportError, match="visibility must be a string"):
        build_export(vault_root=vault, runtime_dir=runtime, kind="public-wiki")

    assert not (runtime / "exports" / "public-wiki").exists()
