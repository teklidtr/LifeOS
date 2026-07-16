"""Conservative migration of legacy experiment notes into canonical artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, cast

from lifeos.daily.service import content_hash
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, iter_vault_markdown, read_vault_markdown

from .artifact import ExperimentArtifactService
from .contracts import (
    EXPERIMENT_SCHEMA_VERSION,
    ExperimentError,
    ExperimentMetadata,
    ExperimentState,
    LifecycleEvent,
    SourceReference,
    protocol_from_dict,
)
from .safety import classify_safety

MigrationState = Literal["ready", "already-migrated", "conflict", "malformed"]


@dataclass(frozen=True, slots=True)
class LegacyExperimentSource:
    path: str
    content_hash: str
    title: str
    source_type: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExperimentMigrationCandidate:
    source: LegacyExperimentSource
    target_path: str | None
    experiment_id: str | None
    state: MigrationState
    diagnostics: tuple[str, ...]
    planned_frontmatter: dict[str, object] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source.to_dict(),
            "target_path": self.target_path,
            "experiment_id": self.experiment_id,
            "state": self.state,
            "diagnostics": list(self.diagnostics),
            "planned_frontmatter": self.planned_frontmatter,
        }


@dataclass(frozen=True, slots=True)
class ExperimentMigrationPreview:
    candidates: tuple[ExperimentMigrationCandidate, ...]

    def to_dict(self) -> dict[str, object]:
        return {"candidates": [item.to_dict() for item in self.candidates]}


@dataclass(frozen=True, slots=True)
class ExperimentMigrationResult:
    state: str
    migrated: tuple[str, ...]
    already_migrated: tuple[str, ...]
    conflicts: tuple[ExperimentMigrationCandidate, ...]
    preserved_sources: tuple[str, ...]
    audit_path: str

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "migrated": list(self.migrated),
            "already_migrated": list(self.already_migrated),
            "conflicts": [item.to_dict() for item in self.conflicts],
            "preserved_sources": list(self.preserved_sources),
            "audit_path": self.audit_path,
        }


def _audit_path(runtime_dir: Path) -> Path:
    return runtime_dir / "experiments" / "migration-audit.json"


def _load_audit(runtime_dir: Path) -> dict[str, dict[str, str]]:
    path = _audit_path(runtime_dir)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
        entries = raw.get("entries", {})
        return {
            str(key): {str(k): str(v) for k, v in dict(value).items()}
            for key, value in dict(entries).items()
        }
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ExperimentError(
            "migration_audit_invalid",
            "Experiment migration audit is malformed.",
            {"error": str(exc)},
        ) from exc


def _write_audit(runtime_dir: Path, entries: Mapping[str, Mapping[str, str]]) -> None:
    path = _audit_path(runtime_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": 1, "entries": {key: dict(value) for key, value in sorted(entries.items())}}
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    os.replace(temp, path)


def _legacy(frontmatter: Mapping[str, Any]) -> bool:
    return (
        frontmatter.get("type") in {"experiment", "personal-experiment-v0"}
        or frontmatter.get("experiment_schema") == 0
    )


def _stable_timestamp(frontmatter: Mapping[str, Any]) -> datetime:
    raw = frontmatter.get("created_at") or frontmatter.get("start_date")
    if not raw:
        raise ExperimentError(
            "legacy_date_missing",
            "Legacy experiment requires created_at or start_date for stable migration identity.",
        )
    text = str(raw)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = datetime.fromisoformat(text + "T00:00:00+00:00")
        except ValueError as exc:
            raise ExperimentError(
                "legacy_date_invalid", "Legacy experiment date is invalid.", {"value": text}
            ) from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _protocol_mapping(frontmatter: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = frontmatter.get("protocol")
    if isinstance(raw, Mapping):
        return raw
    phases = frontmatter.get("phases", ())
    measures = frontmatter.get("measures", frontmatter.get("outcome_measures", ()))
    return {
        "question": frontmatter.get("question", frontmatter.get("title", "")),
        "hypothesis": frontmatter.get("hypothesis", ""),
        "rationale": frontmatter.get("rationale", ""),
        "intervention": frontmatter.get("intervention", ""),
        "constants": frontmatter.get("constants", ()),
        "comparison": frontmatter.get("comparison", frontmatter.get("baseline", "")),
        "baseline_requirements": frontmatter.get("baseline_requirements", ""),
        "outcome_measures": measures,
        "phases": phases,
        "adherence_expectation": frontmatter.get("adherence_expectation", ""),
        "confounders": frontmatter.get("confounders", ()),
        "risks": frontmatter.get("risks", ()),
        "stop_rules": frontmatter.get("stop_rules", ()),
        "success_criteria": frontmatter.get("success_criteria", ()),
        "failure_criteria": frontmatter.get("failure_criteria", ()),
        "inconclusive_criteria": frontmatter.get("inconclusive_criteria", ()),
        "schedule": frontmatter.get("schedule", {}),
    }


def _metadata(
    source_path: str, source_hash: str, frontmatter: Mapping[str, Any]
) -> ExperimentMetadata:
    protocol = protocol_from_dict(_protocol_mapping(frontmatter))
    moment = _stable_timestamp(frontmatter)
    suffix = hashlib.sha256(f"{source_path}\0{source_hash}".encode()).hexdigest()[:8]
    experiment_id = f"exp-{moment.strftime('%Y%m%dT%H%M%SZ')}-{suffix}"
    state_raw = str(frontmatter.get("state", frontmatter.get("status", "idea"))).casefold()
    state = (
        state_raw
        if state_raw
        in {
            "idea",
            "drafting",
            "baseline",
            "scheduled",
            "active",
            "paused",
            "completed",
            "abandoned",
            "analyzed",
            "archived",
        }
        else "idea"
    )
    typed_state = cast(ExperimentState, state)
    created_at = moment.isoformat()
    lifecycle = (
        LifecycleEvent(
            f"life-migration-{suffix}",
            None,
            typed_state,
            created_at,
            f"migrated from {source_path}",
        ),
    )
    return ExperimentMetadata(
        experiment_id=experiment_id,
        title=str(frontmatter.get("title", "Legacy experiment")).strip(),
        description=str(frontmatter.get("description", "")).strip(),
        state=typed_state,
        category=str(frontmatter.get("category", "other")),
        created_at=created_at,
        updated_at=created_at,
        protocol=protocol,
        safety=classify_safety(protocol),
        origins=(SourceReference(source_path, "migrated-from", "sha256:" + source_hash),),
        lifecycle=lifecycle,
        schema_version=EXPERIMENT_SCHEMA_VERSION,
    )


def _target_path(metadata: ExperimentMetadata) -> str:
    slug = (
        "-".join(
            part
            for part in "".join(
                char if char.isalnum() else " " for char in metadata.title.casefold()
            ).split()
        )[:64]
        or "experiment"
    )
    timestamp = metadata.experiment_id.split("-", 2)[1]
    return f"experiments/{timestamp[:4]}/{slug}-{metadata.experiment_id}.md"


def preview_experiment_migration(
    *, vault_root: Path, runtime_dir: Path
) -> ExperimentMigrationPreview:
    audit = _load_audit(runtime_dir)
    candidates: list[ExperimentMigrationCandidate] = []
    try:
        sources = iter_vault_markdown(vault_root, roots=("experiments", "tracking"))
    except VaultAccessError as exc:
        if exc.code == "not-found":
            sources = ()
        else:
            raise ExperimentError(exc.code, str(exc)) from exc
    for source in sources:
        parsed = parse_markdown_note(source.path, content=source.content)
        if not _legacy(parsed.frontmatter):
            continue
        source_hash = content_hash(source.content)
        source_info = LegacyExperimentSource(
            source.relative_path,
            source_hash,
            str(parsed.frontmatter.get("title", source.path.stem)),
            str(parsed.frontmatter.get("type", "experiment_schema:0")),
        )
        diagnostics = tuple(item.message for item in parsed.findings if item.severity == "error")
        if diagnostics:
            candidates.append(
                ExperimentMigrationCandidate(
                    source_info, None, None, "malformed", diagnostics, None
                )
            )
            continue
        try:
            metadata = _metadata(source.relative_path, source_hash, parsed.frontmatter)
            target_path = _target_path(metadata)
        except (ExperimentError, KeyError, TypeError, ValueError) as exc:
            message = getattr(exc, "message", str(exc))
            candidates.append(
                ExperimentMigrationCandidate(source_info, None, None, "malformed", (message,), None)
            )
            continue
        audited = audit.get(source.relative_path)
        state: MigrationState = "ready"
        if audited:
            if (
                audited.get("source_hash") == source_hash
                and (vault_root / audited.get("target_path", "")).exists()
            ):
                state = "already-migrated"
                target_path = audited["target_path"]
            else:
                state = "conflict"
                diagnostics = (
                    "Migration audit exists but the source hash or canonical target no longer matches.",
                )
        elif (vault_root / target_path).exists():
            state = "conflict"
            diagnostics = (
                "Canonical migration target already exists without a matching audit record.",
            )
        candidates.append(
            ExperimentMigrationCandidate(
                source_info,
                target_path,
                metadata.experiment_id,
                state,
                diagnostics,
                metadata.to_frontmatter(),
            )
        )
    return ExperimentMigrationPreview(tuple(candidates))


def apply_experiment_migration(
    *,
    vault_root: Path,
    runtime_dir: Path,
    expected_source_hashes: Mapping[str, str],
    interrupt_after: int | None = None,
) -> ExperimentMigrationResult:
    preview = preview_experiment_migration(vault_root=vault_root, runtime_dir=runtime_dir)
    service = ExperimentArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    audit = _load_audit(runtime_dir)
    migrated: list[str] = []
    already: list[str] = []
    conflicts: list[ExperimentMigrationCandidate] = []
    preserved = tuple(item.source.path for item in preview.candidates)
    processed = 0
    for candidate in preview.candidates:
        expected = expected_source_hashes.get(candidate.source.path)
        if expected != candidate.source.content_hash:
            conflicts.append(
                ExperimentMigrationCandidate(
                    candidate.source,
                    candidate.target_path,
                    candidate.experiment_id,
                    "conflict",
                    (
                        *candidate.diagnostics,
                        "Legacy source changed after preview or was not explicitly approved.",
                    ),
                    candidate.planned_frontmatter,
                )
            )
            continue
        if candidate.state == "already-migrated":
            already.append(candidate.target_path or candidate.source.path)
            continue
        if candidate.state != "ready" or candidate.planned_frontmatter is None:
            conflicts.append(candidate)
            continue
        source = read_vault_markdown(vault_root, candidate.source.path)
        if content_hash(source.content) != candidate.source.content_hash:
            conflicts.append(
                ExperimentMigrationCandidate(
                    candidate.source,
                    candidate.target_path,
                    candidate.experiment_id,
                    "conflict",
                    (*candidate.diagnostics, "Legacy source changed during migration."),
                    candidate.planned_frontmatter,
                )
            )
            continue
        from .contracts import metadata_from_dict

        metadata = metadata_from_dict(candidate.planned_frontmatter)
        human_body = (
            "## Imported legacy note\n\n" + source.content.strip() + "\n\n## User annotations\n\n"
        )
        artifact = service.create_imported(metadata, human_body)
        audit[candidate.source.path] = {
            "source_hash": candidate.source.content_hash,
            "target_path": artifact.path,
            "experiment_id": artifact.metadata.experiment_id,
        }
        _write_audit(runtime_dir, audit)
        migrated.append(artifact.path)
        processed += 1
        if interrupt_after is not None and processed >= interrupt_after:
            return ExperimentMigrationResult(
                "interrupted",
                tuple(migrated),
                tuple(already),
                tuple(conflicts),
                preserved,
                str(_audit_path(runtime_dir)),
            )
    state = "conflict" if conflicts else "ready"
    return ExperimentMigrationResult(
        state,
        tuple(migrated),
        tuple(already),
        tuple(conflicts),
        preserved,
        str(_audit_path(runtime_dir)),
    )
