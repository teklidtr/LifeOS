"""Rebuildable indexes, manifest recovery, and integrity diagnostics for rich capture."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import (
    VaultAccessError,
    VaultMarkdownFile,
    iter_vault_markdown,
    observe_vault_file,
)

from .artifact import (
    AttachmentManifestService,
    CaptureArtifactService,
    capture_path,
    manifest_path,
    parse_capture,
)
from .contracts import AttachmentManifest, CaptureError
from .extraction import LocalExtractionService
from .storage import AttachmentStore

_CHECKPOINT_SCHEMA = 2


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
        return {
            **asdict(self),
            "attachment_ids": list(self.attachment_ids),
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class CaptureIndexReport:
    state: str
    entries: tuple[CaptureIndexEntry, ...]
    diagnostics: tuple[dict[str, object], ...]
    checkpoint_path: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "entries": [item.to_dict() for item in self.entries],
            "diagnostics": [dict(item) for item in self.diagnostics],
            "checkpoint_path": self.checkpoint_path,
        }


@dataclass(frozen=True, slots=True)
class CaptureRecoveryReport:
    state: str
    index: CaptureIndexReport
    diagnostics: tuple[dict[str, object], ...]
    rebuilt_manifests: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "index": self.index.to_dict(),
            "diagnostics": [dict(item) for item in self.diagnostics],
            "rebuilt_manifests": list(self.rebuilt_manifests),
        }


def _index_path(runtime_dir: Path) -> Path:
    return runtime_dir / "captures" / "index.json"


def _checkpoint_path(runtime_dir: Path) -> Path:
    return runtime_dir / "captures" / "rebuild-checkpoint.json"


def _source_signature(sources: tuple[VaultMarkdownFile, ...]) -> str:
    digest = hashlib.sha256()
    for source in sources:
        digest.update(source.relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(source.content_bytes).digest())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _checkpoint_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _discard_checkpoint(checkpoint: Path) -> None:
    checkpoint.unlink(missing_ok=True)
    checkpoint.with_suffix(".tmp").unlink(missing_ok=True)


def _checkpoint_entry(raw: object) -> CaptureIndexEntry:
    if not isinstance(raw, dict):
        raise ValueError("Checkpoint entry must be an object.")
    string_fields = (
        "capture_id",
        "path",
        "content_hash",
        "title",
        "capture_type",
        "state",
        "event_at",
    )
    values: dict[str, str] = {}
    for field in string_fields:
        value = raw.get(field)
        if not isinstance(value, str):
            raise ValueError(f"Checkpoint entry field {field} must be a string.")
        values[field] = value
    attachment_ids = raw.get("attachment_ids")
    tags = raw.get("tags")
    sensitive = raw.get("sensitive")
    if (
        not isinstance(attachment_ids, list)
        or any(not isinstance(value, str) for value in attachment_ids)
        or not isinstance(tags, list)
        or any(not isinstance(value, str) for value in tags)
        or type(sensitive) is not bool
    ):
        raise ValueError("Checkpoint entry has invalid collection fields.")
    return CaptureIndexEntry(
        values["capture_id"],
        values["path"],
        values["content_hash"],
        values["title"],
        values["capture_type"],
        values["state"],
        values["event_at"],
        tuple(attachment_ids),
        tuple(tags),
        sensitive,
    )


def _load_rebuild_checkpoint(
    *, checkpoint: Path, sources: tuple[VaultMarkdownFile, ...], source_signature: str
) -> tuple[int, list[CaptureIndexEntry], list[dict[str, object]]]:
    if not checkpoint.exists():
        return 0, [], []
    try:
        raw = json.loads(checkpoint.read_text())
        if not isinstance(raw, dict) or raw.get("schema") != _CHECKPOINT_SCHEMA:
            raise ValueError("Unsupported capture rebuild checkpoint schema.")
        checkpoint_digest = raw.get("checkpoint_digest")
        unsigned = {key: value for key, value in raw.items() if key != "checkpoint_digest"}
        if (
            not isinstance(checkpoint_digest, str)
            or checkpoint_digest != _checkpoint_digest(unsigned)
        ):
            raise ValueError("Capture rebuild checkpoint integrity is invalid.")
        if raw.get("source_signature") != source_signature or raw.get("source_count") != len(
            sources
        ):
            raise ValueError("Capture rebuild checkpoint sources changed.")
        next_index = raw.get("next_index")
        raw_entries = raw.get("entries")
        raw_diagnostics = raw.get("diagnostics")
        if (
            type(next_index) is not int
            or not 0 <= next_index <= len(sources)
            or not isinstance(raw_entries, list)
            or not isinstance(raw_diagnostics, list)
        ):
            raise ValueError("Capture rebuild checkpoint shape is invalid.")
        entries = [_checkpoint_entry(item) for item in raw_entries]
        diagnostics: list[dict[str, object]] = []
        for item in raw_diagnostics:
            if not isinstance(item, dict) or not isinstance(item.get("code"), str):
                raise ValueError("Capture rebuild checkpoint diagnostic is invalid.")
            diagnostics.append(dict(item))
        processed_sources = {
            source.relative_path: "sha256:" + hashlib.sha256(source.content_bytes).hexdigest()
            for source in sources[:next_index]
        }
        if any(
            processed_sources.get(entry.path) != entry.content_hash
            for entry in entries
        ):
            raise ValueError("Capture rebuild checkpoint entries do not match processed sources.")
        return next_index, entries, diagnostics
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        _discard_checkpoint(checkpoint)
        return 0, [], []


def _write_rebuild_checkpoint(
    *,
    checkpoint: Path,
    source_signature: str,
    source_count: int,
    next_index: int,
    entries: list[CaptureIndexEntry],
    diagnostics: list[dict[str, object]],
) -> None:
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": _CHECKPOINT_SCHEMA,
        "source_signature": source_signature,
        "source_count": source_count,
        "next_index": next_index,
        "entries": [item.to_dict() for item in entries],
        "diagnostics": diagnostics,
    }
    payload["checkpoint_digest"] = _checkpoint_digest(payload)
    temp = checkpoint.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temp, checkpoint)


def _process_capture_source(
    source: VaultMarkdownFile,
) -> tuple[CaptureIndexEntry | None, str | None, dict[str, object] | None]:
    parsed = parse_markdown_note(source.path, content=source.content)
    if parsed.frontmatter.get("type") != "rich-capture":
        return None, None, None
    try:
        artifact = parse_capture(source.path, source.relative_path, source.content)
    except CaptureError as exc:
        return (
            None,
            None,
            {
                "code": "malformed_capture",
                "path": source.relative_path,
                "detail": exc.message,
            },
        )
    metadata = artifact.metadata
    return (
        CaptureIndexEntry(
            metadata.capture_id,
            artifact.path,
            artifact.content_hash,
            metadata.title,
            metadata.capture_type,
            metadata.state,
            metadata.event_at,
            tuple(item.attachment_id for item in metadata.attachments),
            metadata.tags,
            metadata.sensitive,
        ),
        capture_path(metadata),
        None,
    )


def rebuild_capture_index(
    *, vault_root: Path, runtime_dir: Path, batch_size: int = 64, interrupt_after: int | None = None
) -> CaptureIndexReport:
    if batch_size < 1:
        raise CaptureError("invalid_batch_size", "Capture rebuild batch size must be positive.")
    sources = iter_vault_markdown(vault_root)
    checkpoint = _checkpoint_path(runtime_dir)
    source_signature = _source_signature(sources)
    next_index, entries, diagnostics = _load_rebuild_checkpoint(
        checkpoint=checkpoint,
        sources=sources,
        source_signature=source_signature,
    )
    identities: dict[str, str] = {}
    for existing_entry in entries:
        identities.setdefault(existing_entry.capture_id, existing_entry.path)

    processed_this_run = 0
    for source_index in range(next_index, len(sources)):
        source = sources[source_index]
        entry, expected_path, diagnostic = _process_capture_source(source)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        if entry is not None:
            if entry.capture_id in identities:
                diagnostics.append(
                    {
                        "code": "duplicate_identity",
                        "capture_id": entry.capture_id,
                        "paths": [identities[entry.capture_id], entry.path],
                    }
                )
            else:
                identities[entry.capture_id] = entry.path
            if entry.path != expected_path:
                diagnostics.append(
                    {
                        "code": "moved_artifact",
                        "capture_id": entry.capture_id,
                        "path": entry.path,
                        "expected_path": expected_path,
                    }
                )
            entries.append(entry)

        next_index = source_index + 1
        processed_this_run += 1
        if interrupt_after is not None and processed_this_run >= interrupt_after:
            _write_rebuild_checkpoint(
                checkpoint=checkpoint,
                source_signature=source_signature,
                source_count=len(sources),
                next_index=next_index,
                entries=entries,
                diagnostics=diagnostics,
            )
            return CaptureIndexReport(
                "interrupted",
                tuple(entries),
                tuple(diagnostics),
                str(checkpoint.relative_to(runtime_dir)),
            )
        if next_index % batch_size == 0:
            _write_rebuild_checkpoint(
                checkpoint=checkpoint,
                source_signature=source_signature,
                source_count=len(sources),
                next_index=next_index,
                entries=entries,
                diagnostics=diagnostics,
            )

    ordered = tuple(
        sorted(entries, key=lambda item: (item.event_at, item.capture_id), reverse=True)
    )
    path = _index_path(runtime_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "entries": [item.to_dict() for item in ordered],
                "diagnostics": diagnostics,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    _discard_checkpoint(checkpoint)
    return CaptureIndexReport("ready", ordered, tuple(diagnostics))


def load_capture_index(*, runtime_dir: Path) -> CaptureIndexReport:
    path = _index_path(runtime_dir)
    if not path.exists():
        return CaptureIndexReport(
            "missing-index", (), ({"code": "missing_index", "path": str(path)},)
        )
    try:
        raw = json.loads(path.read_text())
        entries = tuple(
            CaptureIndexEntry(
                **{
                    **item,
                    "attachment_ids": tuple(item["attachment_ids"]),
                    "tags": tuple(item["tags"]),
                }
            )
            for item in raw.get("entries", [])
        )
        return CaptureIndexReport(
            "ready", entries, tuple(dict(item) for item in raw.get("diagnostics", []))
        )
    except (OSError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
        return CaptureIndexReport(
            "corrupt-index", (), ({"code": "corrupt_index", "error": str(exc)},)
        )


def rebuild_missing_manifests(*, vault_root: Path, runtime_dir: Path) -> tuple[str, ...]:
    captures = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    manifests = AttachmentManifestService(vault_root=vault_root)
    existing = {item.metadata.attachment_id for item in manifests.list()}
    rebuilt: list[str] = []
    for capture in captures.list():
        for reference in capture.metadata.attachments:
            if reference.attachment_id in existing:
                continue
            try:
                observation = observe_vault_file(
                    vault_root,
                    reference.canonical_path,
                    capture_limit=0,
                )
            except VaultAccessError:
                continue
            audit_hash = "sha256:" + observation.content_hash
            if (
                audit_hash != reference.content_hash
                or observation.size_bytes != reference.byte_size
            ):
                continue
            metadata = AttachmentManifest(
                reference.attachment_id,
                reference.content_hash,
                reference.original_filename,
                reference.canonical_path,
                reference.media_type,
                reference.byte_size,
                "recovery-from-capture-reference",
                capture.metadata.created_at,
                parent_capture_ids=(capture.metadata.capture_id,),
            )
            manifests.create(metadata)
            existing.add(reference.attachment_id)
            rebuilt.append(manifest_path(reference.attachment_id))
    return tuple(rebuilt)


def audit_capture_recovery(
    *,
    vault_root: Path,
    runtime_dir: Path,
    rebuild: bool = False,
    rebuild_manifests: bool = False,
    delete_runtime: bool = False,
    interrupt_after: int | None = None,
    batch_size: int = 64,
) -> CaptureRecoveryReport:
    if delete_runtime:
        shutil.rmtree(runtime_dir / "captures", ignore_errors=True)
    rebuilt = (
        rebuild_missing_manifests(vault_root=vault_root, runtime_dir=runtime_dir)
        if rebuild_manifests
        else ()
    )
    index = (
        rebuild_capture_index(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            batch_size=batch_size,
            interrupt_after=interrupt_after,
        )
        if rebuild
        else load_capture_index(runtime_dir=runtime_dir)
    )
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
                diagnostics.append(
                    {
                        "code": "missing_manifest",
                        "capture_id": capture.metadata.capture_id,
                        "attachment_id": reference.attachment_id,
                        "detail": exc.message,
                    }
                )
                continue
            if manifest.metadata.content_hash != reference.content_hash:
                diagnostics.append(
                    {
                        "code": "manifest_reference_mismatch",
                        "attachment_id": reference.attachment_id,
                        "capture_id": capture.metadata.capture_id,
                    }
                )
            audit = store.audit(reference.attachment_id)
            if audit.status != "ok":
                diagnostics.append(
                    {
                        "code": f"attachment_{audit.status}",
                        "attachment_id": reference.attachment_id,
                        "path": reference.canonical_path,
                        "detail": audit.details,
                    }
                )
            extraction = extractor.load(reference.attachment_id)
            if extraction is not None and extraction.source_hash != reference.content_hash:
                diagnostics.append(
                    {
                        "code": "stale_extraction",
                        "attachment_id": reference.attachment_id,
                        "source_hash": extraction.source_hash,
                        "current_hash": reference.content_hash,
                    }
                )
    manifest_items = manifests.list()
    canonical_paths = {item.metadata.canonical_path for item in manifest_items}
    for manifest in manifest_items:
        if manifest.path != manifest_path(manifest.metadata.attachment_id):
            diagnostics.append(
                {
                    "code": "moved_manifest",
                    "attachment_id": manifest.metadata.attachment_id,
                    "path": manifest.path,
                }
            )
        if manifest.metadata.attachment_id not in referenced:
            diagnostics.append(
                {
                    "code": "orphan_manifest",
                    "attachment_id": manifest.metadata.attachment_id,
                    "path": manifest.path,
                }
            )
    originals_root = vault_root / "attachments" / "originals"
    if originals_root.exists():
        for path in sorted(item for item in originals_root.rglob("*") if item.is_file()):
            relative = path.relative_to(vault_root).as_posix()
            if relative not in canonical_paths:
                diagnostics.append({"code": "orphan_original", "path": relative})
    state = (
        "interrupted"
        if index.state == "interrupted"
        else "needs-review"
        if diagnostics
        else "ready"
    )
    return CaptureRecoveryReport(state, index, tuple(diagnostics), rebuilt)
