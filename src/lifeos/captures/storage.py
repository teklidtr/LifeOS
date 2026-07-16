"""Portable content-addressed attachment storage and reference management."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import secrets
import stat
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from .artifact import AttachmentManifestService, CaptureArtifactService, manifest_path, utc_now
from .contracts import AttachmentManifest, AttachmentReference, CaptureError

_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class AttachmentImportResult:
    reference: AttachmentReference
    manifest_path: str
    duplicate: bool
    reused_original: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "reference": self.reference.to_dict(),
            "manifest_path": self.manifest_path,
            "duplicate": self.duplicate,
            "reused_original": self.reused_original,
        }


@dataclass(frozen=True, slots=True)
class AttachmentAudit:
    attachment_id: str
    status: str
    canonical_path: str
    expected_hash: str
    actual_hash: str | None = None
    details: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "attachment_id": self.attachment_id,
            "status": self.status,
            "canonical_path": self.canonical_path,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "details": self.details,
        }


def _safe_name(value: str) -> str:
    name = Path(value).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return safe[:120] or "attachment.bin"


def _hash_path(path: Path) -> tuple[str, int, int]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise CaptureError("attachment_open_failed", f"Attachment could not be opened: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise CaptureError("unsupported_file", "Only regular files can be attached.")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, _CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise CaptureError("file_changed", "Attachment changed while it was being hashed.")
        return digest.hexdigest(), total, after.st_mtime_ns
    finally:
        os.close(fd)


class AttachmentStore:
    def __init__(self, *, vault_root: Path, runtime_dir: Path) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.manifests = AttachmentManifestService(vault_root=vault_root)
        self.captures = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)

    def import_file(
        self,
        source_path: Path,
        *,
        capture_source: str,
        parent_capture_id: str | None = None,
        independent_copy: bool = False,
        now: datetime | None = None,
    ) -> AttachmentImportResult:
        source = source_path.expanduser()
        digest, byte_size, modified_ns = _hash_path(source)
        content_hash = "sha256:" + digest
        existing = next(
            (item for item in self.manifests.list() if item.metadata.content_hash == content_hash and item.metadata.kind == "original"),
            None,
        )
        if existing is not None and not independent_copy:
            metadata = existing.metadata
            parents = metadata.parent_capture_ids
            if parent_capture_id and parent_capture_id not in parents:
                updated = replace(metadata, parent_capture_ids=(*parents, parent_capture_id))
                existing = self.manifests.save(existing, updated, expected_hash=existing.content_hash)
                metadata = existing.metadata
            return AttachmentImportResult(self._reference(metadata), existing.path, True, True)

        moment = utc_now(now)
        suffix = f"-{secrets.token_hex(3)}" if independent_copy else ""
        relative = f"attachments/originals/{digest[:2]}/{digest}{suffix}/{_safe_name(source.name)}"
        target = self.vault_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            self._copy_atomic(source, target)
        actual, actual_size, _ = _hash_path(target)
        if actual != digest or actual_size != byte_size:
            target.unlink(missing_ok=True)
            raise CaptureError("storage_verification_failed", "Stored attachment did not match the original bytes.")
        attachment_id = f"att-{digest[:16]}" if not independent_copy else f"att-{secrets.token_hex(8)}"
        metadata = AttachmentManifest(
            attachment_id=attachment_id,
            content_hash=content_hash,
            original_filename=source.name,
            canonical_path=relative,
            media_type=mimetypes.guess_type(source.name)[0] or "application/octet-stream",
            byte_size=byte_size,
            capture_source=capture_source.strip() or "unknown",
            imported_at=moment.isoformat(),
            parent_capture_ids=(parent_capture_id,) if parent_capture_id else (),
            duplicate_of=existing.metadata.attachment_id if existing is not None else None,
            source_modified_ns=modified_ns,
        )
        artifact = self.manifests.create(metadata)
        return AttachmentImportResult(self._reference(metadata), artifact.path, existing is not None, False)

    def attach_to_capture(
        self, capture_path_value: str, reference: AttachmentReference, *, expected_hash: str, now: datetime | None = None
    ) -> object:
        artifact = self.captures.load(capture_path_value)
        if any(item.attachment_id == reference.attachment_id for item in artifact.metadata.attachments):
            return artifact
        moment = utc_now(now)
        metadata = replace(
            artifact.metadata,
            attachments=(*artifact.metadata.attachments, reference),
            updated_at=moment.isoformat(),
        )
        return self.captures.save(artifact, metadata, expected_hash=expected_hash)

    def remove_from_capture(
        self, capture_path_value: str, attachment_id: str, *, expected_hash: str, now: datetime | None = None
    ) -> object:
        artifact = self.captures.load(capture_path_value)
        selected = tuple(item for item in artifact.metadata.attachments if item.attachment_id != attachment_id)
        if len(selected) == len(artifact.metadata.attachments):
            raise CaptureError("attachment_not_linked", "Attachment is not linked to this capture.")
        moment = utc_now(now)
        metadata = replace(artifact.metadata, attachments=selected, updated_at=moment.isoformat())
        return self.captures.save(artifact, metadata, expected_hash=expected_hash)

    def delete_original_if_unreferenced(self, attachment_id: str) -> bool:
        manifest = self.manifests.load(manifest_path(attachment_id))
        references = [
            item.metadata.capture_id
            for item in self.captures.list()
            if any(ref.attachment_id == attachment_id for ref in item.metadata.attachments)
        ]
        if references:
            raise CaptureError("attachment_referenced", "Attachment is still referenced.", {"capture_ids": references})
        original = self.vault_root / manifest.metadata.canonical_path
        original.unlink(missing_ok=True)
        return True

    def audit(self, attachment_id: str) -> AttachmentAudit:
        manifest = self.manifests.load(manifest_path(attachment_id))
        original = self.vault_root / manifest.metadata.canonical_path
        if not original.exists():
            return AttachmentAudit(attachment_id, "missing", manifest.metadata.canonical_path, manifest.metadata.content_hash, details="Original file is missing.")
        try:
            digest, size, _ = _hash_path(original)
        except CaptureError as exc:
            return AttachmentAudit(attachment_id, exc.code, manifest.metadata.canonical_path, manifest.metadata.content_hash, details=exc.message)
        actual = "sha256:" + digest
        if actual != manifest.metadata.content_hash or size != manifest.metadata.byte_size:
            return AttachmentAudit(attachment_id, "changed", manifest.metadata.canonical_path, manifest.metadata.content_hash, actual, "Original bytes changed; derivatives are stale.")
        return AttachmentAudit(attachment_id, "ok", manifest.metadata.canonical_path, manifest.metadata.content_hash, actual)

    @staticmethod
    def _reference(metadata: AttachmentManifest) -> AttachmentReference:
        return AttachmentReference(
            metadata.attachment_id,
            manifest_path(metadata.attachment_id),
            metadata.content_hash,
            metadata.media_type,
            metadata.byte_size,
            metadata.original_filename,
            metadata.canonical_path,
        )

    @staticmethod
    def _copy_atomic(source: Path, target: Path) -> None:
        directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        temp_name = f".{target.name}.{secrets.token_hex(6)}.import"
        temp_fd = -1
        source_fd = -1
        try:
            source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            temp_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644, dir_fd=directory_fd)
            while True:
                chunk = os.read(source_fd, _CHUNK_SIZE)
                if not chunk:
                    break
                offset = 0
                while offset < len(chunk):
                    offset += os.write(temp_fd, chunk[offset:])
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = -1
            os.replace(temp_name, target.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
        except OSError as exc:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except OSError:
                pass
            raise CaptureError("storage_write_failure", f"Attachment could not be stored: {exc}") from exc
        finally:
            if temp_fd >= 0:
                os.close(temp_fd)
            if source_fd >= 0:
                os.close(source_fd)
            os.close(directory_fd)
