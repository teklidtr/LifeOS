import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

DEFAULT_OWNERSHIP_MANIFEST_PATH = PurePosixPath("system/generated-ownership.json")


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

            # Simple check for absolute / traversal in manifest
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
        # Protect manifest path from symlinks
        norm_manifest = Path(os.path.normpath(str(manifest_path)))

        # For simplicity, resolve each parent up to root
        for parent in list(norm_manifest.parents)[::-1] + [norm_manifest]:
            if parent.is_symlink():
                raise PathSafetyError(f"Manifest path or parent is a symlink: {parent}")

        if not manifest_path.exists():
            return cls(manifest_path, vault_root, {})

        try:
            content_bytes = manifest_path.read_bytes()
        except OSError as e:
            raise ManifestError(f"Failed to read manifest file: {e}") from e

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
        is_existing = resolved_target.exists()

        if is_existing:
            if not existing_entry:
                raise UnownedFileError(f"Target {rel_path} exists but is unowned")
            if existing_entry.generator_id != generator_id:
                raise GeneratorMismatchError(
                    f"Target owned by {existing_entry.generator_id}, not {generator_id}"
                )

            current_hash = stream_sha256(resolved_target)
            if current_hash != existing_entry.content_hash:
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
            is_new=not is_existing,
        )

    def _update_and_save_manifest(
        self,
        rel_path: str,
        new_entry: ManifestEntry,
        write_target: bool,
        resolved_target: Path,
        content: bytes,
        is_new: bool,
    ) -> None:
        import shutil
        import uuid

        backup_target = None
        unique_suffix = uuid.uuid4().hex
        if write_target and not is_new:
            # Backup original target to a unique tmp file
            backup_target = resolved_target.with_name(
                f"{resolved_target.name}.{unique_suffix}.backup.tmp"
            )
            try:
                shutil.copy2(resolved_target, backup_target)
            except Exception as e:
                if backup_target.exists():
                    backup_target.unlink()
                raise PersistenceError(f"Failed to create target backup: {e}") from e

        old_entry = self._entries.get(rel_path)
        self._entries[rel_path] = new_entry

        if write_target:
            resolved_target.parent.mkdir(parents=True, exist_ok=True)
            # Write new target content to a unique tmp file
            temp_target = resolved_target.with_name(f"{resolved_target.name}.{unique_suffix}.tmp")
            try:
                temp_target.write_bytes(content)
                os.replace(temp_target, resolved_target)
            except Exception as e:
                # Rollback memory on target write failure
                if old_entry:
                    self._entries[rel_path] = old_entry
                else:
                    del self._entries[rel_path]
                if temp_target.exists():
                    temp_target.unlink()
                if backup_target and backup_target.exists():
                    backup_target.unlink()
                raise PersistenceError(f"Failed to write target file: {e}") from e

        try:
            self._save_manifest()
        except Exception as e:
            # Rollback target if manifest save fails
            rollback_err = None
            if write_target:
                try:
                    if is_new:
                        if resolved_target.exists():
                            resolved_target.unlink()
                    else:
                        if backup_target and backup_target.exists():
                            os.replace(backup_target, resolved_target)  # Atomic restoration
                except Exception as r_err:
                    rollback_err = r_err

            # Rollback memory
            if old_entry:
                self._entries[rel_path] = old_entry
            else:
                del self._entries[rel_path]

            if rollback_err:
                # Do not unlink backup if rollback failed, to preserve it for manual recovery
                raise PersistenceError(
                    f"Manifest save failed, AND rollback failed: {rollback_err} (Original error: {e}). "
                    f"Backup file preserved at: {backup_target}"
                ) from e

            if backup_target and backup_target.exists():
                backup_target.unlink()

            raise PersistenceError(f"Manifest persistence failed, changes rolled back: {e}") from e

        # Post-commit cleanup: Manifest and target successfully committed
        if backup_target and backup_target.exists():
            try:
                backup_target.unlink()
            except Exception as e:
                raise PersistenceError(
                    f"Target and manifest committed successfully, but failed to clean up backup file: {e}"
                ) from e
