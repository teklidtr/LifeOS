from __future__ import annotations

import json
from pathlib import Path

from lifeos.exports import build_export, export_status
from lifeos.publication import active_generation_path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_export_status_rejects_cross_kind_manifest(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    runtime_dir = tmp_path / "runtime"
    _write(vault_root / "wiki" / "note.md", "---\ntitle: Note\n---\nbody\n")
    build_export(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        kind="public-wiki",
    )
    active = active_generation_path(runtime_dir / "exports" / "public-wiki")
    assert active is not None
    manifest_path = active / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["kind"] = "study-bundle"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert (
        export_status(vault_root=vault_root, runtime_dir=runtime_dir, kind="public-wiki").status
        == "failed"
    )
