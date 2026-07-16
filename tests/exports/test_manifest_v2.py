from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lifeos.exports import ExportError, build_export, load_export_manifest


def _write(vault: Path, relative: str, content: str) -> Path:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _build(vault: Path, kind: str = "public-wiki") -> tuple[Path, dict[str, object]]:
    result = build_export(vault_root=vault, runtime_dir=vault / ".lifeos", kind=kind)
    output = vault / ".lifeos" / result.output_dir
    return output, json.loads((output / "manifest.json").read_text(encoding="utf-8"))


def _entry(manifest: dict[str, object], source_path: str) -> dict[str, object]:
    files = manifest["files"]
    assert isinstance(files, list)
    return next(item for item in files if item["source_path"] == source_path)


def test_manifest_separates_canonical_and_rendered_hashes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    source = _write(vault, "wiki/nested/source.md", "See [[wiki/target|Target]].\n")
    _write(vault, "wiki/target.md", "Target.\n")

    output, manifest = _build(vault)

    item = _entry(manifest, "wiki/nested/source.md")
    rendered = (output / "wiki/nested/source.md").read_bytes()
    assert item["source_hash"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert item["rendered_hash"] == hashlib.sha256(rendered).hexdigest()
    assert item["source_hash"] != item["rendered_hash"]
    assert item["source_size"] == len(source.read_bytes())
    assert item["rendered_size"] == len(rendered)


def test_rendering_change_updates_only_rendered_hash(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    source = _write(vault, "wiki/source.md", "See [[target|Target]].\n")

    first_output, first_manifest = _build(vault)
    first_entry = _entry(first_manifest, "wiki/source.md")
    assert (first_output / "wiki/source.md").read_text(encoding="utf-8") == "See Target.\n"

    _write(vault, "wiki/target.md", "Target.\n")
    second_output, second_manifest = _build(vault)
    second_entry = _entry(second_manifest, "wiki/source.md")

    assert source.read_text(encoding="utf-8") == "See [[target|Target]].\n"
    assert first_entry["source_hash"] == second_entry["source_hash"]
    assert first_entry["rendered_hash"] != second_entry["rendered_hash"]
    assert "[Target](target.md)" in (second_output / "wiki/source.md").read_text(encoding="utf-8")


def test_nested_links_resolve_relative_to_referring_output(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(
        vault,
        "wiki/guides/deep/source.md",
        "[[wiki/guides/deep/sibling|Sibling]]\n"
        "[[wiki/guides/parent|Parent]]\n"
        "[[wiki/reference/deeper/target|Deep]].\n",
    )
    _write(vault, "wiki/guides/deep/sibling.md", "Sibling.\n")
    _write(vault, "wiki/guides/parent.md", "Parent.\n")
    _write(vault, "wiki/reference/deeper/target.md", "Target.\n")

    output, _manifest = _build(vault)
    rendered = (output / "wiki/guides/deep/source.md").read_text(encoding="utf-8")

    assert "[Sibling](sibling.md)" in rendered
    assert "[Parent](../parent.md)" in rendered
    assert "[Deep](../../reference/deeper/target.md)" in rendered


def test_ambiguous_basename_is_not_resolved_by_traversal_order(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault, "wiki/source.md", "See [[same|Same]].\n")
    _write(vault, "wiki/a/same.md", "A.\n")
    _write(vault, "wiki/b/same.md", "B.\n")

    output, manifest = _build(vault)
    rendered = (output / "wiki/source.md").read_text(encoding="utf-8")
    diagnostics = manifest["diagnostics"]

    assert rendered == "See Same.\n"
    assert isinstance(diagnostics, list)
    assert [item["code"] for item in diagnostics] == ["export-link-ambiguous"]


def test_exact_path_disambiguates_duplicate_basenames(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault, "wiki/source.md", "See [[wiki/b/same|Chosen]].\n")
    _write(vault, "wiki/a/same.md", "A.\n")
    _write(vault, "wiki/b/same.md", "B.\n")

    output, manifest = _build(vault)

    assert "[Chosen](b/same.md)" in (output / "wiki/source.md").read_text(encoding="utf-8")
    assert manifest["diagnostics"] == []


def test_heading_and_block_fragments_are_normalized_and_uri_encoded(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(
        vault,
        "wiki/source.md",
        "[[wiki/target#Café & ATP? 50%|Heading]]\n"
        "[[wiki/target#^block id/ü|Block]].\n",
    )
    _write(vault, "wiki/target.md", "# Café & ATP? 50%\nBlock ^block id/ü\n")

    output, _manifest = _build(vault)
    rendered = (output / "wiki/source.md").read_text(encoding="utf-8")

    assert "[Heading](target.md#caf%C3%A9-atp-50)" in rendered
    assert "[Block](target.md#%5Eblock%20id%2F%C3%BC)" in rendered


def test_private_link_diagnostic_does_not_disclose_private_path(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault, "wiki/public.md", "See [[wiki/private/secret-plan|Secret]].\n")
    _write(vault, "wiki/private/secret-plan.md", "---\nvisibility: private\n---\nHidden.\n")

    output, manifest = _build(vault)
    rendered = (output / "wiki/public.md").read_text(encoding="utf-8")
    diagnostics = manifest["diagnostics"]

    assert rendered == "See Secret.\n"
    assert isinstance(diagnostics, list)
    assert diagnostics[0]["code"] == "export-link-private"
    serialized = json.dumps(diagnostics)
    assert "secret-plan" not in serialized
    assert "wiki/private" not in serialized


def test_manifest_and_rendered_markdown_are_byte_deterministic(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault, "wiki/nested/source.md", "See [[wiki/target#A Heading|Target]].\n")
    _write(vault, "wiki/target.md", "# A Heading\n")

    first_output, _first_manifest = _build(vault)
    first_manifest_bytes = (first_output / "manifest.json").read_bytes()
    first_markdown = (first_output / "wiki/nested/source.md").read_bytes()
    second_output, _second_manifest = _build(vault)

    assert (second_output / "manifest.json").read_bytes() == first_manifest_bytes
    assert (second_output / "wiki/nested/source.md").read_bytes() == first_markdown


def test_manifest_loader_rejects_version_one_with_rebuild_guidance(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text('{"schema_version": 1}\n', encoding="utf-8")

    with pytest.raises(ExportError, match="rebuilt as version 2"):
        load_export_manifest(path)


def test_manifest_loader_validates_hashes_sizes_and_policy(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault, "wiki/note.md", "Note.\n")
    output, _manifest = _build(vault)
    path = output / "manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))

    raw["files"][0]["source_hash"] = "not-a-hash"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ExportError, match="source_hash"):
        load_export_manifest(path)

    raw["files"][0]["source_hash"] = hashlib.sha256(b"Note.\n").hexdigest()
    raw["files"][0]["source_size"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ExportError, match="source_size"):
        load_export_manifest(path)

    raw["files"][0]["source_size"] = len(b"Note.\n")
    raw["rendering_policy_version"] = "unknown"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ExportError, match="rendering policy"):
        load_export_manifest(path)
