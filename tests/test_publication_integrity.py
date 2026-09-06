from __future__ import annotations

import hashlib
import json
import os
import socket
from pathlib import Path

import pytest

from lifeos.config import FeatureFlags, LifeOSConfig
from lifeos.exports import build_export, export_status
from lifeos.graph import build_graph_view, graph_view_status
from lifeos.publication import (
    active_generation_path,
    inspect_generation_integrity,
    publish_generation,
)
from lifeos.registry import Registry
from lifeos.status import collect_status


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _active(root: Path) -> Path:
    active = active_generation_path(root)
    assert active is not None
    return active


def _build_graph_and_export(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    _write(
        vault / "wiki" / "note.md",
        "---\nid: note\ntitle: Note\nvisibility: public\n---\nBody.\n",
    )
    build_graph_view(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    build_export(vault_root=vault, runtime_dir=runtime, kind="public-wiki")
    graph = _active(runtime / "graphify" / "knowledge")
    export = _active(runtime / "exports" / "public-wiki")
    return vault, runtime, graph, export


def _snapshot(path: Path) -> dict[str, tuple[int, int, str]]:
    result: dict[str, tuple[int, int, str]] = {}
    for root, directories, files in os.walk(path):
        directories.sort()
        files.sort()
        for name in files:
            item = Path(root) / name
            metadata = item.stat()
            result[item.relative_to(path).as_posix()] = (
                metadata.st_size,
                metadata.st_mtime_ns,
                hashlib.sha256(item.read_bytes()).hexdigest(),
            )
    return result


def test_valid_publications_have_verifiable_integrity(tmp_path: Path) -> None:
    vault, runtime, graph, export = _build_graph_and_export(tmp_path)

    assert inspect_generation_integrity(graph).state == "valid"
    assert inspect_generation_integrity(export).state == "valid"
    assert (
        graph_view_status(vault_root=vault, runtime_dir=runtime, view_name="knowledge").status
        == "clean"
    )
    assert (
        export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki").status == "ready"
    )


@pytest.mark.parametrize("relative_path", ["graph.json", "state.json"])
def test_missing_graph_payload_or_state_fails_status(tmp_path: Path, relative_path: str) -> None:
    vault, runtime, graph, _export = _build_graph_and_export(tmp_path)
    (graph / relative_path).unlink()

    state = graph_view_status(vault_root=vault, runtime_dir=runtime, view_name="knowledge")

    assert state.status == "failed"
    assert state.integrity_state == "corrupt"


@pytest.mark.parametrize("relative_path", ["manifest.json", "wiki/note.md"])
def test_missing_export_manifest_or_payload_fails_status(
    tmp_path: Path, relative_path: str
) -> None:
    vault, runtime, _graph, export = _build_graph_and_export(tmp_path)
    (export / relative_path).unlink()

    state = export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki")

    assert state.status == "failed"
    assert state.integrity_state == "corrupt"


def test_modified_graph_and_export_payloads_fail_closed(tmp_path: Path) -> None:
    vault, runtime, graph, export = _build_graph_and_export(tmp_path)
    (graph / "graph.json").write_text("{}", encoding="utf-8")
    (export / "wiki" / "note.md").write_text("tampered\n", encoding="utf-8")

    graph_state = graph_view_status(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    export_state = export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki")

    assert graph_state.status == "failed"
    assert graph_state.integrity_state == "corrupt"
    assert export_state.status == "failed"
    assert export_state.integrity_state == "corrupt"


@pytest.mark.parametrize("product", ["graph", "export"])
def test_unexpected_extra_file_fails_product_status(tmp_path: Path, product: str) -> None:
    vault, runtime, graph, export = _build_graph_and_export(tmp_path)
    generation = graph if product == "graph" else export
    (generation / "unexpected.txt").write_text("extra", encoding="utf-8")

    if product == "graph":
        status = graph_view_status(
            vault_root=vault, runtime_dir=runtime, view_name="knowledge"
        ).status
    else:
        status = export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki").status

    assert status == "failed"


@pytest.mark.parametrize("product", ["graph", "export"])
def test_symlinked_payload_is_never_followed(tmp_path: Path, product: str) -> None:
    vault, runtime, graph, export = _build_graph_and_export(tmp_path)
    generation = graph if product == "graph" else export
    target_path = generation / ("graph.json" if product == "graph" else "wiki/note.md")
    external = tmp_path / "external-secret"
    external.write_text("external", encoding="utf-8")
    target_path.unlink()
    target_path.symlink_to(external)

    if product == "graph":
        state = graph_view_status(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    else:
        state = export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki")

    assert state.status == "failed"
    assert state.integrity_state == "corrupt"
    assert external.read_text(encoding="utf-8") == "external"


@pytest.mark.parametrize("entry_kind", ["directory", "fifo", "socket"])
def test_special_payload_entries_are_rejected(tmp_path: Path, entry_kind: str) -> None:
    root = tmp_path / entry_kind
    publish_generation(root=root, files={"payload": b"original"})
    generation = _active(root)
    payload = generation / "payload"
    payload.unlink()

    listener: socket.socket | None = None
    if entry_kind == "directory":
        payload.mkdir()
    elif entry_kind == "fifo":
        os.mkfifo(payload)
    else:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        short_socket = Path("/tmp") / f"lifeos-{os.getpid()}-{tmp_path.name}.sock"
        short_socket.unlink(missing_ok=True)
        listener.bind(str(short_socket))
        short_socket.replace(payload)

    try:
        inspection = inspect_generation_integrity(generation)
    finally:
        if listener is not None:
            listener.close()

    assert inspection.state == "corrupt"


@pytest.mark.parametrize("replacement", [b"short", b"altered!"])
def test_size_and_same_size_hash_mismatches_are_detected(
    tmp_path: Path, replacement: bytes
) -> None:
    root = tmp_path / "publication"
    publish_generation(root=root, files={"payload": b"original"})
    generation = _active(root)
    (generation / "payload").write_bytes(replacement)

    inspection = inspect_generation_integrity(generation)

    assert inspection.state == "corrupt"


@pytest.mark.parametrize("corruption", ["traversal", "duplicate"])
def test_inventory_path_traversal_and_duplicates_are_corrupt(
    tmp_path: Path, corruption: str
) -> None:
    root = tmp_path / "publication"
    publish_generation(root=root, files={"payload": b"original"})
    generation = _active(root)
    path = generation / "integrity.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if corruption == "traversal":
        raw["files"][0]["path"] = "../outside"
    else:
        raw["files"].append(dict(raw["files"][0]))
    path.write_text(json.dumps(raw), encoding="utf-8")

    inspection = inspect_generation_integrity(generation)

    assert inspection.state == "corrupt"


def test_pre_inventory_generation_requires_rebuild(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    generation = root / "generations" / "legacy"
    generation.mkdir(parents=True)
    (generation / "payload").write_text("legacy", encoding="utf-8")
    (root / "active.json").write_text(
        json.dumps({"schema_version": 1, "generation_id": "legacy"}),
        encoding="utf-8",
    )

    inspection = inspect_generation_integrity(generation)

    assert inspection.state == "unsupported"
    assert inspection.code == "integrity-inventory-missing"


def test_product_status_marks_pre_inventory_generations_unsupported(tmp_path: Path) -> None:
    vault, runtime, graph, export = _build_graph_and_export(tmp_path)
    (graph / "integrity.json").unlink()
    (export / "integrity.json").unlink()

    graph_state = graph_view_status(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    export_state = export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki")

    assert graph_state.status == "unsupported"
    assert graph_state.integrity_code == "integrity-inventory-missing"
    assert export_state.status == "unsupported"
    assert export_state.integrity_code == "integrity-inventory-missing"


def test_integrity_storage_unavailability_is_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "publication"
    publish_generation(root=root, files={"payload": b"original"})
    generation = _active(root)

    def unavailable(_fd: int) -> list[str]:
        raise PermissionError("denied")

    monkeypatch.setattr(os, "listdir", unavailable)

    inspection = inspect_generation_integrity(generation)

    assert inspection.state == "unavailable"
    assert inspection.code == "integrity-storage-unavailable"


def test_status_aggregation_reports_graph_corruption_and_export_staleness(
    tmp_path: Path,
) -> None:
    vault, runtime, graph, _export = _build_graph_and_export(tmp_path)
    (graph / "graph.json").write_text("{}", encoding="utf-8")
    (vault / "wiki" / "note.md").write_text(
        "---\nid: note\ntitle: Note\nvisibility: public\n---\nChanged.\n",
        encoding="utf-8",
    )
    registry = Registry(runtime / "registry.db")
    registry.initialize()
    result = collect_status(
        LifeOSConfig(vault, runtime, FeatureFlags(graphify=True, exports=True)),
        registry,
    )
    checks = {check.subsystem: check for check in result.checks}

    assert checks["graph"].state == "corrupt"
    assert checks["graph"].code == "graph-publication-corrupt"
    assert checks["exports"].state == "stale"
    assert checks["exports"].code == "exports-stale"


def test_integrity_status_is_read_only_and_deterministic(tmp_path: Path) -> None:
    vault, runtime, _graph, _export = _build_graph_and_export(tmp_path)
    before = _snapshot(runtime)
    graph_root = runtime / "graphify" / "knowledge"
    export_root = runtime / "exports" / "public-wiki"
    graph_pointer = (graph_root / "active.json").read_bytes()
    export_pointer = (export_root / "active.json").read_bytes()

    first_graph = graph_view_status(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    first_export = export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki")
    second_graph = graph_view_status(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    second_export = export_status(vault_root=vault, runtime_dir=runtime, kind="public-wiki")

    assert first_graph == second_graph
    assert first_export == second_export
    assert _snapshot(runtime) == before
    assert (graph_root / "active.json").read_bytes() == graph_pointer
    assert (export_root / "active.json").read_bytes() == export_pointer


def test_top_level_status_requires_rebuild_for_pre_inventory_products(
    tmp_path: Path,
) -> None:
    vault, runtime, graph, export = _build_graph_and_export(tmp_path)
    (graph / "integrity.json").unlink()
    (export / "integrity.json").unlink()
    registry = Registry(runtime / "registry.db")
    registry.initialize()

    result = collect_status(
        LifeOSConfig(vault, runtime, FeatureFlags(graphify=True, exports=True)),
        registry,
    )
    checks = {check.subsystem: check for check in result.checks}

    assert checks["graph"].state == "stale"
    assert checks["graph"].code == "graph-rebuild-required"
    assert checks["exports"].state == "stale"
    assert checks["exports"].code == "exports-rebuild-required"
