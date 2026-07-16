"""Rebuildable indexes, manifest recovery, and integrity diagnostics for rich capture."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import iter_vault_markdown

from .artifact import AttachmentManifestService, CaptureArtifactService, capture_path, manifest_path, parse_capture, parse_manifest
from .contracts import AttachmentManifest, CaptureArtifact, CaptureError
from .extraction import LocalExtractionService
from .storage import AttachmentStore, _hash_path


@dataclass(frozen=True, slots=True)
class CaptureIndexEntry:
    capture_id: str
    path: str
    content_hash: str
    title: str
    capture_type: str
    state: str
    event_at: str
    attachment_ids: tuple[str, ...]
    tags: tuple[str, ...]
    sensitive: bool

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "attachment_ids": list(self.attachment_ids), "tags": list(self.tags)}


@dataclass(frozen=True, slots=True)
class CaptureIndexReport:
    state: str
    entries: tuple[CaptureIndexEntry, ...]
    diagnostics: tuple[dict[str, object], ...]
    checkpoint_path: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"state": self.state, "entries": [item.to_dict() for item in self.entries], "diagnostics": [dict(item) for item in self.diagnostics], "checkpoint_path": self.checkpoint_path}


@dataclass(frozen=True, slots=True)
class CaptureRecoveryReport:
    state: str
    index: CaptureIndexReport
    diagnostics: tuple[dict[str, object], ...]
    rebuilt_manifests: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {"state": self.state, "index": self.index.to_dict(), "diagnostics": [dict(item) for item in self.diagnostics], "rebuilt_manifests": list(self.rebuilt_manifests)}


def _index_path(runtime_dir: Path) -> Path:
    return runtime_dir / "captures" / "index.json"


def _checkpoint_path(runtime_dir: Path) -> Path:
    return runtime_dir / "captures" / "rebuild-checkpoint.json"


def _all_capture_artifacts(vault_root: Path) -> tuple[tuple[CaptureArtifact, ...], tuple[dict[str, object], ...]]:
    found: list[CaptureArtifact] = []
    diagnostics: list[dict[str, object]] = []
    for source in iter_vault_markdown(vault_root):
        parsed = parse_markdown_note(source.path, content=source.content)
        if parsed.frontmatter.get("type") != "rich-capture":
            continue
        try:
            found.append(parse_capture(source.path, source.relative_path, source.content))
        except CaptureError as exc:
            diagnostics.append({"code": "malformed_capture", "path": source.relative_path, "detail": exc.message})
    return tuple(found), tuple(diagnostics)


def rebuild_capture_index(*, vault_root: Path, runtime_dir: Path, batch_size: int = 64, interrupt_after: int | None = None) -> CaptureIndexReport:
    if batch_size < 1:
        raise CaptureError("invalid_batch_size", "Capture rebuild batch size must be positive.")
    artifacts, parse_diagnostics = _all_capture_artifacts(vault_root)
    entries: list[CaptureIndexEntry] = []
    diagnostics: list[dict[str, object]] = list(parse_diagnostics)
    identities: dict[str, str] = {}
    checkpoint = _checkpoint_path(runtime_dir)
    for index, artifact in enumerate(artifacts):
        metadata = artifact.metadata
        if metadata.capture_id in identities:
            diagnostics.append({"code": "duplicate_identity", "capture_id": metadata.capture_id, "paths": [identities[metadata.capture_id], artifact.path]})
        else:
            identities[metadata.capture_id] = artifact.path
        expected = capture_path(metadata)
        if artifact.path != expected:
            diagnostics.append({"code": "moved_artifact", "capture_id": metadata.capture_id, "path": artifact.path, "expected_path": expected})
        entries.append(CaptureIndexEntry(metadata.capture_id, artifact.path, artifact.content_hash, metadata.title, metadata.capture_type, metadata.state, metadata.event_at, tuple(item.attachment_id for item in metadata.attachments), metadata.tags, metadata.sensitive))
        if interrupt_after is not None and index + 1 >= interrupt_after:
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_text(json.dumps({"schema": 1, "processed": index + 1, "total": len(artifacts)}, indent=2, sort_keys=True) + "\n")
            return CaptureIndexReport("interrupted", tuple(entries), tuple(diagnostics), str(checkpoint.relative_to(runtime_dir)))
        if (index + 1) % batch_size == 0:
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_text(json.dumps({"schema": 1, "processed": index + 1, "total": len(artifacts)}, indent=2, sort_keys=True) + "\n")
    ordered = tuple(sorted(entries, key=lambda item: (item.event_at, item.capture_id), reverse=True))
    path = _index_path(runtime_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "entries": [item.to_dict() for item in ordered], "diagnostics": diagnostics}, indent=2, sort_keys=True) + "\n")
    checkpoint.unlink(missing_ok=True)
    return CaptureIndexReport("ready", ordered, tuple(diagnostics))


def load_capture_index(*, runtime_dir: Path) -> CaptureIndexReport:
    path = _index_path(runtime_dir)
    if not path.exists():
        return CaptureIndexReport("missing-index", (), ({"code": "missing_index", "path": str(path)},))
    try:
        raw = json.loads(path.read_text())
        entries = tuple(CaptureIndexEntry(**{**item, "attachment_ids": tuple(item["attachment_ids"]), "tags": tuple(item["tags"])}) for item in raw.get("entries", []))
        return CaptureIndexReport("ready", entries, tuple(dict(item) for item in raw.get("diagnostics", [])))
    except (OSError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
        return CaptureIndexReport("corrupt-index", (), ({"code": "corrupt_index", "error": str(exc)},))


def rebuild_missing_manifests(*, vault_root: Path, runtime_dir: Path) -> tuple[str, ...]:
    captures = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    manifests = AttachmentManifestService(vault_root=vault_root)
    existing = {item.metadata.attachment_id for item in manifests.list()}
    rebuilt: list[str] = []
    for capture in captures.list():
        for reference in capture.metadata.attachments:
            if reference.attachment_id in existing:
                continue
            original = vault_root / reference.canonical_path
            if not original.exists():
                continue
            digest, byte_size, _ = _hash_path(original)
            audit_hash = "sha256:" + digest
            if audit_hash != reference.content_hash or byte_size != reference.byte_size:
                continue
            metadata = AttachmentManifest(reference.attachment_id, reference.content_hash, reference.original_filename, reference.canonical_path, reference.media_type, reference.byte_size, "recovery-from-capture-reference", capture.metadata.created_at, parent_capture_ids=(capture.metadata.capture_id,))
            manifests.create(metadata)
            existing.add(reference.attachment_id)
            rebuilt.append(manifest_path(reference.attachment_id))
    return tuple(rebuilt)


def audit_capture_recovery(*, vault_root: Path, runtime_dir: Path, rebuild: bool = False, rebuild_manifests: bool = False, delete_runtime: bool = False, interrupt_after: int | None = None, batch_size: int = 64) -> CaptureRecoveryReport:
    if delete_runtime:
        shutil.rmtree(runtime_dir / "captures", ignore_errors=True)
    rebuilt = rebuild_missing_manifests(vault_root=vault_root, runtime_dir=runtime_dir) if rebuild_manifests else ()
    index = rebuild_capture_index(vault_root=vault_root, runtime_dir=runtime_dir, batch_size=batch_size, interrupt_after=interrupt_after) if rebuild else load_capture_index(runtime_dir=runtime_dir)
    diagnostics: list[dict[str, object]] = list(index.diagnostics)
    captures = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    manifests = AttachmentManifestService(vault_root=vault_root)
    store = AttachmentStore(vault_root=vault_root, runtime_dir=runtime_dir)
    extractor = LocalExtractionService(vault_root=vault_root, runtime_dir=runtime_dir)
    referenced: set[str] = set()
    for capture in captures.list():
        for reference in capture.metadata.attachments:
            referenced.add(reference.attachment_id)
            try:
                manifest = manifests.load(reference.manifest_path)
            except CaptureError as exc:
                diagnostics.append({"code": "missing_manifest", "capture_id": capture.metadata.capture_id, "attachment_id": reference.attachment_id, "detail": exc.message})
                continue
            if manifest.metadata.content_hash != reference.content_hash:
                diagnostics.append({"code": "manifest_reference_mismatch", "attachment_id": reference.attachment_id, "capture_id": capture.metadata.capture_id})
            audit = store.audit(reference.attachment_id)
            if audit.status != "ok":
                diagnostics.append({"code": f"attachment_{audit.status}", "attachment_id": reference.attachment_id, "path": reference.canonical_path, "detail": audit.details})
            extraction = extractor.load(reference.attachment_id)
            if extraction is not None and extraction.source_hash != reference.content_hash:
                diagnostics.append({"code": "stale_extraction", "attachment_id": reference.attachment_id, "source_hash": extraction.source_hash, "current_hash": reference.content_hash})
    manifest_items = manifests.list()
    canonical_paths = {item.metadata.canonical_path for item in manifest_items}
    for manifest in manifest_items:
        if manifest.path != manifest_path(manifest.metadata.attachment_id):
            diagnostics.append({"code": "moved_manifest", "attachment_id": manifest.metadata.attachment_id, "path": manifest.path})
        if manifest.metadata.attachment_id not in referenced:
            diagnostics.append({"code": "orphan_manifest", "attachment_id": manifest.metadata.attachment_id, "path": manifest.path})
    originals_root = vault_root / "attachments" / "originals"
    if originals_root.exists():
        for path in sorted(item for item in originals_root.rglob("*") if item.is_file()):
            relative = path.relative_to(vault_root).as_posix()
            if relative not in canonical_paths:
                diagnostics.append({"code": "orphan_original", "path": relative})
    state = "interrupted" if index.state == "interrupted" else "needs-review" if diagnostics else "ready"
    return CaptureRecoveryReport(state, index, tuple(diagnostics), rebuilt)
