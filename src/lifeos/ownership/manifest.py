import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping

from lifeos._transaction_files import (
    BackupFile,
    ParentDescriptor,
    StagingFile,
    TransactionError,
    cleanup_backup,
    cleanup_staging,
    create_hardlink_backup,
    create_staging_file,
    get_target_identity,
    publish_creation,
    publish_replacement,
    rollback_creation,
    rollback_replacement,
)
from lifeos.vault import (
    VaultAccessError,
    VaultFileObservation,
    observe_vault_file,
    open_or_create_vault_directory,
)

DEFAULT_OWNERSHIP_MANIFEST_PATH = PurePosixPath("system/generated-ownership.json")

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


class OwnershipError(Exception):
    pass


class UnownedFileError(OwnershipError):
    pass


class GeneratorMismatchError(OwnershipError):
    pass


class ExternalModificationError(OwnershipError):
    pass


class ManifestError(OwnershipError):
    pass


class PathSafetyError(OwnershipError):
    pass


class PersistenceError(OwnershipError):
    pass


HASH_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class ManifestEntry:
    generator_id: str
    generator_version: str
    content_hash: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.generator_id, str) or not self.generator_id.strip():
            raise ManifestError("Invalid generator_id")
        if not isinstance(self.generator_version, str) or not self.generator_version.strip():
            raise ManifestError("Invalid generator_version")
        if not isinstance(self.content_hash, str) or not HASH_RE.match(self.content_hash):
            raise ManifestError("Invalid content_hash")
        if not isinstance(self.created_at, str) or not isinstance(self.updated_at, str):
            raise ManifestError("Timestamps must be strings")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def stream_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    d: dict[str, Any] = {}
    for k, v in pairs:
        if k in d:
            raise ManifestError(f"Duplicate JSON key found: {k}")
        d[k] = v
    return d


def _absolute_descriptor_path(path: Path) -> tuple[Path, str]:
    """Return one filesystem-root descriptor anchor plus a portable relative path."""
    absolute_path = Path(os.path.abspath(path))
    root = Path(absolute_path.anchor)
    relative_parts = absolute_path.parts[len(root.parts) :]
    relative_path = PurePosixPath(*relative_parts).as_posix() if relative_parts else "."
    return root, relative_path


def _read_manifest_bytes(manifest_path: Path) -> bytes | None:
    root, relative_path = _absolute_descriptor_path(manifest_path)
    if relative_path == ".":
        raise ManifestError("Manifest path must name a file")
    try:
        return observe_vault_file(root, relative_path).captured_bytes
    except VaultAccessError as exc:
        if exc.code == "not-found":
            return None
        if exc.code == "unsafe-symlink":
            unsafe_path = root / exc.relative_path
            raise PathSafetyError(
                f"Manifest path or parent is a symlink: {unsafe_path}"
            ) from exc
        if exc.code in {"unsafe-file-type", "invalid-path", "invalid-root"}:
            raise PathSafetyError(f"Manifest path cannot be read safely: {manifest_path}") from exc
        raise ManifestError(f"Failed to read manifest file: {exc}") from exc


def serialize_generated_ownership_bytes(
    entries: Mapping[str, ManifestEntry],
) -> bytes:
    data = {
        "schema_version": 1,
        "owned_files": {
            p: {
                "generator_id": e.generator_id,
                "generator_version": e.generator_version,
                "content_hash": e.content_hash,
                "created_at": e.created_at,
                "updated_at": e.updated_at,
            }
            for p, e in entries.items()
        },
    }
    return json.dumps(data, sort_keys=True, indent=2).encode("utf-8")


class GeneratedOwnership:
    def __init__(
        self, manifest_path: Path, vault_root: Path, entries: dict[str, ManifestEntry]
    ) -> None:
        self.manifest_path = manifest_path
        self.vault_root = vault_root.resolve(strict=True)
        self._entries = entries

    @property
    def entries(self) -> Mapping[str, ManifestEntry]:
        import types

        return types.MappingProxyType(self._entries)

    @classmethod
    def from_bytes(
        cls, data: bytes, *, manifest_path: Path, vault_root: Path
    ) -> "GeneratedOwnership":
        try:
            content = data.decode("utf-8")
            json_data = json.loads(content, object_pairs_hook=_reject_duplicates)
        except UnicodeDecodeError as e:
            raise ManifestError("Manifest bytes are not valid UTF-8") from e
        except json.JSONDecodeError as e:
            raise ManifestError(f"Malformed JSON: {e}") from e
        except ManifestError:
            raise
        except Exception as e:
            raise ManifestError(f"Failed to read manifest: {e}") from e

        if not isinstance(json_data, dict):
            raise ManifestError("Manifest must be a JSON object")

        if json_data.get("schema_version") != 1:
            raise ManifestError(f"Unsupported schema version: {json_data.get('schema_version')}")

        owned_files = json_data.get("owned_files")
        if not isinstance(owned_files, dict):
            raise ManifestError("owned_files must be a dictionary")

        entries: dict[str, ManifestEntry] = {}
        for p_str, entry_data in owned_files.items():
            if not isinstance(entry_data, dict):
                raise ManifestError(f"Invalid entry data for path {p_str}")

            norm_p = os.path.normpath(p_str)
            if norm_p in entries:
                raise ManifestError(f"Duplicate normalized path in manifest: {norm_p}")

            if os.path.isabs(norm_p) or norm_p.startswith("../") or norm_p == "..":
                raise ManifestError(f"Unsafe path in manifest: {norm_p}")

            try:
                entry = ManifestEntry(
                    generator_id=entry_data.get("generator_id"),  # type: ignore
                    generator_version=entry_data.get("generator_version"),  # type: ignore
                    content_hash=entry_data.get("content_hash"),  # type: ignore
                    created_at=entry_data.get("created_at"),  # type: ignore
                    updated_at=entry_data.get("updated_at"),  # type: ignore
                )
            except ManifestError as e:
                raise ManifestError(f"Invalid entry for {norm_p}: {e}") from e

            entries[norm_p] = entry

        return cls(manifest_path, vault_root, entries)

    @classmethod
    def load(cls, manifest_path: Path, vault_root: Path) -> "GeneratedOwnership":
        content_bytes = _read_manifest_bytes(manifest_path)
        if content_bytes is None:
            return cls(manifest_path, vault_root, {})
        return cls.from_bytes(content_bytes, manifest_path=manifest_path, vault_root=vault_root)

    def _check_path_safety(self, target: Path) -> tuple[Path, str]:
        norm_str = os.path.normpath(str(target))
        norm_target = Path(norm_str)

        if norm_target.is_absolute():
            raise PathSafetyError("Target path must be relative")

        current = self.vault_root
        for part in norm_target.parts:
            if part == "..":
                raise PathSafetyError("Path traversal not allowed")
            current = current / part
            if current.is_symlink():
                raise PathSafetyError(f"Symlinks are not allowed: {current}")

        rel_path = current.relative_to(self.vault_root).as_posix()
        return current, rel_path

    def _observe_existing_target(self, rel_path: str) -> VaultFileObservation | None:
        try:
            return observe_vault_file(self.vault_root, rel_path, capture_limit=0)
        except VaultAccessError as exc:
            if exc.code == "not-found":
                return None
            if exc.code == "concurrent-change":
                raise ExternalModificationError(
                    f"Target {rel_path} changed while it was being verified"
                ) from exc
            raise PathSafetyError(f"Target {rel_path} cannot be inspected safely") from exc

    @contextmanager
    def _target_parent(
        self, rel_path: str, *, create_missing: bool
    ) -> Iterator[ParentDescriptor]:
        parent_relative = PurePosixPath(rel_path).parent.as_posix()
        absolute_parent = self.vault_root / Path(parent_relative)
        authority_root, authority_relative = _absolute_descriptor_path(absolute_parent)
        try:
            authority_fd = os.open(authority_root, _DIRECTORY_FLAGS)
        except OSError as exc:
            raise PathSafetyError(f"Target {rel_path} cannot be inspected safely") from exc

        parent_fd = -1
        try:
            if parent_relative == ".":
                try:
                    parent_fd = os.open(self.vault_root, _DIRECTORY_FLAGS)
                except OSError as exc:
                    raise PathSafetyError(
                        f"Target {rel_path} cannot be inspected safely"
                    ) from exc
                observed = os.fstat(parent_fd)
                yield ParentDescriptor(
                    fd=parent_fd,
                    dev=observed.st_dev,
                    ino=observed.st_ino,
                    path=authority_relative,
                    authority_fd=authority_fd,
                )
            else:
                try:
                    with open_or_create_vault_directory(
                        self.vault_root,
                        parent_relative,
                        create_missing=create_missing,
                    ) as opened_parent:
                        observed = os.fstat(opened_parent)
                        yield ParentDescriptor(
                            fd=opened_parent,
                            dev=observed.st_dev,
                            ino=observed.st_ino,
                            path=authority_relative,
                            authority_fd=authority_fd,
                        )
                except VaultAccessError as exc:
                    raise PathSafetyError(
                        f"Target {rel_path} cannot be inspected safely"
                    ) from exc
        finally:
            if parent_fd >= 0:
                os.close(parent_fd)
            os.close(authority_fd)

    def _save_manifest(self) -> None:
        json_bytes = serialize_generated_ownership_bytes(self._entries)

        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        import uuid

        temp_manifest = self.manifest_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            with temp_manifest.open("wb") as f:
                f.write(json_bytes)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_manifest, self.manifest_path)
        except Exception as e:
            if temp_manifest.exists():
                temp_manifest.unlink()
            raise PersistenceError(f"Manifest persistence failed: {e}") from e

    def write_generated_file(
        self,
        target_path: Path | str,
        content: bytes,
        generator_id: str,
        generator_version: str,
    ) -> None:
        if not generator_id or not generator_id.strip():
            raise ManifestError("generator_id must not be empty")
        if not generator_version or not generator_version.strip():
            raise ManifestError("generator_version must not be empty")

        target = Path(target_path)
        resolved_target, rel_path = self._check_path_safety(target)

        new_hash = hashlib.sha256(content).hexdigest()

        existing_entry = self._entries.get(rel_path)
        observation = self._observe_existing_target(rel_path)

        if observation is not None:
            if not existing_entry:
                raise UnownedFileError(f"Target {rel_path} exists but is unowned")
            if existing_entry.generator_id != generator_id:
                raise GeneratorMismatchError(
                    f"Target owned by {existing_entry.generator_id}, not {generator_id}"
                )

            if observation.content_hash != existing_entry.content_hash:
                raise ExternalModificationError(f"Target {rel_path} has been modified externally")

            if new_hash == existing_entry.content_hash:
                if generator_version == existing_entry.generator_version:
                    return

                new_entry = replace(
                    existing_entry, generator_version=generator_version, updated_at=utcnow()
                )
                self._update_and_save_manifest(
                    rel_path,
                    new_entry,
                    write_target=False,
                    resolved_target=resolved_target,
                    content=content,
                    is_new=False,
                    expected_target_hash=observation.content_hash,
                )
                return

        now = utcnow()
        created_at = existing_entry.created_at if existing_entry else now

        new_entry = ManifestEntry(
            generator_id=generator_id,
            generator_version=generator_version,
            content_hash=new_hash,
            created_at=created_at,
            updated_at=now,
        )

        self._update_and_save_manifest(
            rel_path,
            new_entry,
            write_target=True,
            resolved_target=resolved_target,
            content=content,
            is_new=observation is None,
            expected_target_hash=observation.content_hash if observation is not None else None,
        )

    def _update_and_save_manifest(
        self,
        rel_path: str,
        new_entry: ManifestEntry,
        write_target: bool,
        resolved_target: Path,
        content: bytes,
        is_new: bool,
        expected_target_hash: str | None,
    ) -> None:
        old_entry = self._entries.get(rel_path)

        if not write_target:
            self._entries[rel_path] = new_entry
            try:
                self._save_manifest()
            except Exception as exc:
                if old_entry:
                    self._entries[rel_path] = old_entry
                else:
                    del self._entries[rel_path]
                raise PersistenceError(
                    f"Manifest persistence failed, changes rolled back: {exc}"
                ) from exc
            return

        target_name = PurePosixPath(rel_path).name
        with self._target_parent(rel_path, create_missing=is_new) as parent:
            staging: StagingFile | None = None
            backup: BackupFile | None = None

            try:
                try:
                    current_identity = get_target_identity(target_name, parent)
                except TransactionError as exc:
                    raise PathSafetyError(
                        f"Target {rel_path} cannot be inspected safely"
                    ) from exc

                if is_new:
                    if current_identity is not None:
                        if old_entry is None:
                            raise UnownedFileError(f"Target {rel_path} exists but is unowned")
                        raise ExternalModificationError(
                            f"Target {rel_path} changed before it could be regenerated"
                        )
                    intended_mode = None
                else:
                    if (
                        expected_target_hash is None
                        or current_identity is None
                        or current_identity.content_hash != expected_target_hash
                    ):
                        raise ExternalModificationError(
                            f"Target {rel_path} changed before mutation"
                        )
                    intended_mode = stat.S_IMODE(current_identity.mode)

                try:
                    staging = create_staging_file(
                        target_name,
                        content,
                        parent,
                        intended_mode,
                    )
                except TransactionError as exc:
                    raise PersistenceError(f"Failed to write target file: {exc}") from exc

                if is_new:
                    try:
                        publish_creation(target_name, staging)
                    except TransactionError as exc:
                        observed_after_failure = self._observe_existing_target(rel_path)
                        if observed_after_failure is not None:
                            if old_entry is None:
                                raise UnownedFileError(
                                    f"Target {rel_path} exists but is unowned"
                                ) from exc
                            raise ExternalModificationError(
                                f"Target {rel_path} changed before creation"
                            ) from exc
                        raise PersistenceError(f"Failed to write target file: {exc}") from exc
                else:
                    assert current_identity is not None
                    try:
                        backup = create_hardlink_backup(
                            target_name,
                            parent,
                            current_identity,
                        )
                    except TransactionError as exc:
                        observed_after_failure = self._observe_existing_target(rel_path)
                        if (
                            observed_after_failure is None
                            or observed_after_failure.content_hash != expected_target_hash
                        ):
                            raise ExternalModificationError(
                                f"Target {rel_path} changed before backup"
                            ) from exc
                        raise PersistenceError(
                            f"Failed to create target backup: {exc}"
                        ) from exc

                    assert backup is not None
                    try:
                        publish_replacement(target_name, staging, current_identity)
                    except TransactionError as exc:
                        observed_after_failure = self._observe_existing_target(rel_path)
                        if (
                            observed_after_failure is None
                            or observed_after_failure.content_hash != expected_target_hash
                        ):
                            raise ExternalModificationError(
                                f"Target {rel_path} changed during mutation"
                            ) from exc
                        cleanup_error: Exception | None = None
                        try:
                            cleanup_backup(backup)
                            backup = None
                        except Exception as cleanup_exc:
                            cleanup_error = cleanup_exc
                        if cleanup_error is not None:
                            raise PersistenceError(
                                "Failed to write target file and clean up backup: "
                                f"{exc}; cleanup failed: {cleanup_error}"
                            ) from exc
                        raise PersistenceError(f"Failed to write target file: {exc}") from exc

                assert staging is not None
                self._entries[rel_path] = new_entry
                try:
                    self._save_manifest()
                except Exception as exc:
                    rollback_error: Exception | None = None
                    try:
                        if is_new:
                            rollback_creation(target_name, staging)
                        else:
                            assert backup is not None
                            rollback_replacement(target_name, staging, backup)
                    except Exception as rollback_exc:
                        rollback_error = rollback_exc

                    if old_entry:
                        self._entries[rel_path] = old_entry
                    else:
                        del self._entries[rel_path]

                    if rollback_error is not None:
                        backup_path = (
                            resolved_target.parent / backup.name
                            if backup is not None
                            else None
                        )
                        preserved = (
                            f" Backup file preserved at: {backup_path}"
                            if backup_path is not None
                            else ""
                        )
                        raise PersistenceError(
                            "Manifest save failed, AND rollback failed: "
                            f"{rollback_error} (Original error: {exc}).{preserved}"
                        ) from exc

                    raise PersistenceError(
                        f"Manifest persistence failed, changes rolled back: {exc}"
                    ) from exc

                if backup is not None:
                    try:
                        cleanup_backup(backup)
                    except Exception as exc:
                        raise PersistenceError(
                            "Target and manifest committed successfully, but failed "
                            f"to clean up backup file: {exc}"
                        ) from exc
            finally:
                if staging is not None:
                    try:
                        cleanup_staging(staging)
                    except (FileNotFoundError, OSError):
                        pass
