"""Conservative rich-capture migration discovery.

The current repository has no pre-existing canonical meal, workout, or attachment-capture
schema. Migration therefore exposes an explicit, audited no-op path rather than inventing
legacy formats.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .contracts import CaptureError


@dataclass(frozen=True, slots=True)
class CaptureMigrationPreview:
    candidates: tuple[dict[str, object], ...]
    legacy_formats_found: tuple[str, ...]
    finding: str

    def to_dict(self) -> dict[str, object]:
        return {"candidates": [dict(item) for item in self.candidates], "legacy_formats_found": list(self.legacy_formats_found), "finding": self.finding}


@dataclass(frozen=True, slots=True)
class CaptureMigrationResult:
    state: str
    migrated: tuple[str, ...]
    already_migrated: tuple[str, ...]
    conflicts: tuple[dict[str, object], ...]
    preserved_sources: tuple[str, ...]
    audit_path: str
    finding: str

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "migrated": list(self.migrated), "already_migrated": list(self.already_migrated), "conflicts": [dict(item) for item in self.conflicts], "preserved_sources": list(self.preserved_sources)}


def preview_capture_migration(*, vault_root: Path, runtime_dir: Path) -> CaptureMigrationPreview:
    del vault_root, runtime_dir
    return CaptureMigrationPreview((), (), "No repository-defined legacy rich-capture, meal-capture, workout-capture, or attachment-capture schema was found. Migration is a documented no-op.")


def apply_capture_migration(*, vault_root: Path, runtime_dir: Path, expected_source_hashes: Mapping[str, str] | None = None) -> CaptureMigrationResult:
    del vault_root
    hashes = dict(expected_source_hashes or {})
    if hashes:
        raise CaptureError("unknown_legacy_source", "No supported legacy rich-capture sources exist, so supplied source hashes cannot be applied.", {"paths": sorted(hashes)})
    audit = runtime_dir / "captures" / "migration-audit.json"
    audit.parent.mkdir(parents=True, exist_ok=True)
    finding = "No migration was required; no legacy format was invented and no source file was changed."
    audit.write_text(json.dumps({"schema": 1, "applied_at": datetime.now(timezone.utc).isoformat(), "state": "not-required", "finding": finding}, indent=2, sort_keys=True) + "\n")
    return CaptureMigrationResult("not-required", (), (), (), (), str(audit.relative_to(runtime_dir)), finding)
