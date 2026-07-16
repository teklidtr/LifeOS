"""Canonical adaptive-feedback preferences and explicit corrections."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Literal

import yaml

from lifeos._atomic_write import atomic_write_file_secure
from lifeos.daily.errors import DailyInteractionError
from lifeos.daily.service import (
    _atomic_write,
    _frontmatter_document,
    _read_existing,
    content_hash,
)
from lifeos.feedback.models import FeedbackObservation
from lifeos.vault import VaultAccessError, read_vault_text

PREFERENCES_SCHEMA_VERSION = 1
_ALLOWED_DIMENSIONS = frozenset({"duration", "energy", "motivation", "mode", "duration_band", "time_window", "blocker", "avoidance"})
_ALLOWED_MODES = frozenset({"off", "shadow", "active"})
_ALLOWED_OUTCOMES = frozenset(
    {"started", "done", "partial", "skipped", "deferred", "cancelled", "unaccounted"}
)
_CURRENT_KEYS = frozenset(
    {
        "schema_version",
        "mode",
        "disabled_dimensions",
        "excluded_event_ids",
        "dismissed_diagnoses",
        "reset",
    }
)
_LEGACY_KEYS = frozenset(
    {"schema_version", "enabled", "disabled_signals", "excluded_events"}
)


@dataclass(frozen=True, slots=True)
class AdaptivePreferences:
    schema_version: int = PREFERENCES_SCHEMA_VERSION
    mode: Literal["off", "shadow", "active"] = "off"
    disabled_dimensions: tuple[str, ...] = ()
    excluded_event_ids: tuple[str, ...] = ()
    dismissed_diagnoses: tuple[tuple[str, str], ...] = ()
    reset_before: date | None = None
    reset_reason: str | None = None
    content_hash: str | None = None

    def dismissed_fingerprints(self) -> tuple[str, ...]:
        return tuple(value for _, value in self.dismissed_diagnoses)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PreferencesUpdate:
    idempotency_key: str
    expected_hash: str | None
    mode: Literal["off", "shadow", "active"] | None = None
    disabled_dimensions: tuple[str, ...] | None = None
    exclude_event_id: str | None = None
    include_event_id: str | None = None
    dismiss_diagnosis_id: str | None = None
    dismiss_fingerprint: str | None = None
    restore_diagnosis_id: str | None = None
    reset_before: date | None = None
    reset_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PreferencesMigrationResult:
    state: Literal["missing", "current", "migratable", "migrated"]
    from_version: int | None
    to_version: int
    changed: bool
    dry_run: bool
    mode: Literal["off", "shadow", "active"]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_preferences(
    observations: Iterable[FeedbackObservation],
    preferences: AdaptivePreferences,
) -> tuple[FeedbackObservation, ...]:
    """Apply canonical exclusions and reset boundaries to derived observations."""

    excluded = set(preferences.excluded_event_ids)
    result = []
    for item in observations:
        reset_excluded = (
            preferences.reset_before is not None
            and item.day < preferences.reset_before
        )
        result.append(
            replace(
                item,
                excluded=(item.excluded or item.event_id in excluded or reset_excluded),
            )
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class OutcomeCorrection:
    idempotency_key: str
    plan_path: str
    corrects_event_id: str
    outcome: str
    day: date
    expected_hash: str
    actual_minutes: int | None = None
    completion_fraction: float | None = None
    reason: str | None = None


class FeedbackControlService:
    def __init__(self, *, vault_root: Path, runtime_dir: Path, actor_id: str) -> None:
        self.vault_root = vault_root.resolve()
        self.runtime_dir = runtime_dir.resolve()
        self.actor_id = actor_id

    @property
    def preferences_path(self) -> Path:
        return self.vault_root / "system" / "adaptive-planning.yml"

    def _read_preferences_content(self) -> str | None:
        try:
            return read_vault_text(
                self.vault_root, "system/adaptive-planning.yml"
            ).content
        except VaultAccessError as exc:
            if exc.code == "not-found":
                return None
            remediation = (
                "Replace the symlink with a regular vault file."
                if exc.code in {"unsafe-symlink", "unsafe-file-type"}
                else "Check vault storage and permissions."
            )
            raise DailyInteractionError(
                "unsafe_path"
                if exc.code in {"unsafe-symlink", "unsafe-file-type"}
                else "storage_unavailable",
                str(exc),
                remediation,
                {"path": exc.relative_path, "vault_code": exc.code},
            ) from exc

    @staticmethod
    def _mapping(content: str) -> dict[str, Any]:
        try:
            loaded = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Adaptive preferences are invalid YAML.",
                "Repair system/adaptive-planning.yml.",
            ) from exc
        if not isinstance(loaded, dict) or not all(
            isinstance(key, str) for key in loaded
        ):
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Adaptive preferences must be a mapping with string keys.",
                "Repair system/adaptive-planning.yml.",
            )
        return loaded

    def load(self) -> AdaptivePreferences:
        raw_content = self._read_preferences_content()
        if raw_content is None:
            return AdaptivePreferences()
        raw = self._mapping(raw_content)
        schema_version = raw.get("schema_version")
        if type(schema_version) is not int or schema_version != PREFERENCES_SCHEMA_VERSION:
            raise DailyInteractionError(
                "unsupported_feedback_preferences",
                "Adaptive preferences require an explicit compatible schema.",
                "Preview and run the adaptive preference migration.",
            )
        unknown = sorted(set(raw) - _CURRENT_KEYS)
        if unknown:
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Adaptive preferences contain unexpected fields.",
                "Repair system/adaptive-planning.yml.",
                {"fields": unknown},
            )
        mode = raw.get("mode", "off")
        disabled = raw.get("disabled_dimensions", [])
        excluded = raw.get("excluded_event_ids", [])
        dismissed = raw.get("dismissed_diagnoses", {})
        reset = raw.get("reset", {})
        if mode not in _ALLOWED_MODES:
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Adaptive mode is invalid.",
                "Choose off, shadow, or active.",
            )
        if not isinstance(disabled, list) or not all(
            isinstance(item, str) and item in _ALLOWED_DIMENSIONS
            for item in disabled
        ):
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Disabled dimensions are invalid.",
                "Repair the preferences file.",
            )
        if not isinstance(excluded, list) or not all(
            isinstance(item, str) and item for item in excluded
        ):
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Excluded event IDs are invalid.",
                "Repair the preferences file.",
            )
        if not isinstance(dismissed, dict) or not all(
            isinstance(key, str)
            and key
            and isinstance(value, str)
            and value
            for key, value in dismissed.items()
        ):
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Dismissed diagnoses are invalid.",
                "Repair the preferences file.",
            )
        if not isinstance(reset, dict):
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Reset marker is invalid.",
                "Repair the preferences file.",
            )
        reset_unknown = sorted(set(reset) - {"before", "reason"})
        if reset_unknown:
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Reset marker contains unexpected fields.",
                "Repair the preferences file.",
                {"fields": reset_unknown},
            )
        reset_before = None
        value = reset.get("before")
        if value is not None:
            try:
                reset_before = value if type(value) is date else date.fromisoformat(value)
            except (TypeError, ValueError) as exc:
                raise DailyInteractionError(
                    "invalid_feedback_preferences",
                    "Reset date is invalid.",
                    "Repair the preferences file.",
                ) from exc
        reason_value = reset.get("reason")
        if reason_value is not None and not isinstance(reason_value, str):
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Reset reason must be text.",
                "Repair the preferences file.",
            )
        reset_reason = reason_value.strip() if isinstance(reason_value, str) else None
        return AdaptivePreferences(
            PREFERENCES_SCHEMA_VERSION,
            mode,
            tuple(sorted(set(disabled))),
            tuple(sorted(set(excluded))),
            tuple(sorted(dismissed.items())),
            reset_before,
            reset_reason or None,
            content_hash(raw_content),
        )

    def migrate(self, *, dry_run: bool = True) -> PreferencesMigrationResult:
        raw_content = self._read_preferences_content()
        if raw_content is None:
            return PreferencesMigrationResult(
                "missing", None, PREFERENCES_SCHEMA_VERSION, False, dry_run, "off"
            )
        raw = self._mapping(raw_content)
        raw_version = raw.get("schema_version", 0)
        if type(raw_version) is int and raw_version == PREFERENCES_SCHEMA_VERSION:
            current = self.load()
            return PreferencesMigrationResult(
                "current",
                PREFERENCES_SCHEMA_VERSION,
                PREFERENCES_SCHEMA_VERSION,
                False,
                dry_run,
                current.mode,
            )
        if type(raw_version) is not int or raw_version != 0:
            raise DailyInteractionError(
                "unsupported_feedback_preferences",
                "Adaptive preferences use an unsupported schema.",
                "Install a compatible LifeOS version or restore the previous file.",
            )
        unknown = sorted(set(raw) - _LEGACY_KEYS)
        if unknown:
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Legacy adaptive preferences contain unexpected fields.",
                "Repair system/adaptive-planning.yml.",
                {"fields": unknown},
            )
        enabled = raw.get("enabled", False)
        if not isinstance(enabled, bool):
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Legacy enabled must be true or false.",
                "Repair system/adaptive-planning.yml.",
            )
        disabled = raw.get("disabled_signals", [])
        excluded = raw.get("excluded_events", [])
        if not isinstance(disabled, list) or not all(
            isinstance(item, str) and item in _ALLOWED_DIMENSIONS for item in disabled
        ):
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Legacy disabled signals are invalid.",
                "Repair system/adaptive-planning.yml.",
            )
        if not isinstance(excluded, list) or not all(
            isinstance(item, str) and item for item in excluded
        ):
            raise DailyInteractionError(
                "invalid_feedback_preferences",
                "Legacy excluded events are invalid.",
                "Repair system/adaptive-planning.yml.",
            )
        mode: Literal["off", "shadow", "active"] = "shadow" if enabled else "off"
        if dry_run:
            return PreferencesMigrationResult(
                "migratable", 0, PREFERENCES_SCHEMA_VERSION, True, True, mode
            )
        document = {
            "schema_version": PREFERENCES_SCHEMA_VERSION,
            "mode": mode,
            "disabled_dimensions": sorted(set(disabled)),
            "excluded_event_ids": sorted(set(excluded)),
            "dismissed_diagnoses": {},
            "reset": {},
        }
        serialized = yaml.safe_dump(document, sort_keys=True, allow_unicode=True)
        _atomic_write(
            self.vault_root,
            "system/adaptive-planning.yml",
            serialized,
            expected_hash=content_hash(raw_content),
            create=False,
        )
        return PreferencesMigrationResult(
            "migrated", 0, PREFERENCES_SCHEMA_VERSION, True, False, mode
        )

    def _cache(self, key: str, fingerprint: str, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        cache = self.runtime_dir / "feedback" / "idempotency" / f"{key}.json"
        if result is None:
            try:
                raw = json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            if raw.get("fingerprint") != fingerprint:
                raise DailyInteractionError("idempotency_conflict", "The idempotency key was reused with different data.", "Retry with a new key.")
            return raw.get("result")
        cache.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"fingerprint": fingerprint, "result": result}, sort_keys=True, default=str).encode("utf-8")
        dir_fd = os.open(cache.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            atomic_write_file_secure(dir_fd, cache.name, payload)
        finally:
            os.close(dir_fd)
        return result

    def update(self, request: PreferencesUpdate) -> AdaptivePreferences:
        fingerprint = hashlib.sha256(json.dumps(asdict(request), sort_keys=True, default=str).encode()).hexdigest()
        cached = self._cache(request.idempotency_key, fingerprint)
        if cached is not None:
            return self.load()
        current = self.load()
        if request.expected_hash != current.content_hash:
            raise DailyInteractionError("stale_write", "Adaptive preferences changed after they were read.", "Reload feedback settings and retry.")
        mode = request.mode or current.mode
        if mode not in _ALLOWED_MODES:
            raise DailyInteractionError("invalid_mode", "Adaptive mode is invalid.", "Choose off, shadow, or active.")
        disabled = set(current.disabled_dimensions if request.disabled_dimensions is None else request.disabled_dimensions)
        if not disabled <= _ALLOWED_DIMENSIONS:
            raise DailyInteractionError("invalid_dimension", "An adaptive feedback dimension is invalid.", "Choose a supported dimension.")
        excluded = set(current.excluded_event_ids)
        if request.exclude_event_id:
            excluded.add(request.exclude_event_id)
        if request.include_event_id:
            excluded.discard(request.include_event_id)
        dismissed = dict(current.dismissed_diagnoses)
        if request.dismiss_diagnosis_id or request.dismiss_fingerprint:
            if not request.dismiss_diagnosis_id or not request.dismiss_fingerprint:
                raise DailyInteractionError("invalid_dismissal", "Diagnosis ID and evidence fingerprint are both required.", "Reload the diagnosis and retry.")
            dismissed[request.dismiss_diagnosis_id] = request.dismiss_fingerprint
        if request.restore_diagnosis_id:
            dismissed.pop(request.restore_diagnosis_id, None)
        reset_before = request.reset_before if request.reset_before is not None else current.reset_before
        reset_reason = request.reset_reason if request.reset_before is not None else current.reset_reason
        document = {
            "schema_version": PREFERENCES_SCHEMA_VERSION,
            "mode": mode,
            "disabled_dimensions": sorted(disabled),
            "excluded_event_ids": sorted(excluded),
            "dismissed_diagnoses": dict(sorted(dismissed.items())),
            "reset": ({"before": reset_before, "reason": reset_reason} if reset_before else {}),
        }
        serialized = yaml.safe_dump(document, sort_keys=True, allow_unicode=True)
        _atomic_write(
            self.vault_root,
            "system/adaptive-planning.yml",
            serialized,
            expected_hash=current.content_hash,
            create=current.content_hash is None,
        )
        updated = self.load()
        self._cache(request.idempotency_key, fingerprint, updated.to_dict())
        return updated

    def correct_outcome(self, request: OutcomeCorrection) -> dict[str, Any]:
        if request.outcome not in _ALLOWED_OUTCOMES:
            raise DailyInteractionError("invalid_outcome", "Corrected outcome is invalid.", "Choose a supported outcome.")
        if request.actual_minutes is not None and (type(request.actual_minutes) is not int or not 0 <= request.actual_minutes <= 1440):
            raise DailyInteractionError("invalid_duration", "Actual minutes must be from 0 to 1440.", "Correct the duration.")
        if request.completion_fraction is not None and (isinstance(request.completion_fraction, bool) or not 0 <= request.completion_fraction <= 1):
            raise DailyInteractionError("invalid_completion_fraction", "Completion fraction must be from 0 to 1.", "Correct the fraction.")
        fingerprint = hashlib.sha256(json.dumps(asdict(request), sort_keys=True, default=str).encode()).hexdigest()
        cached = self._cache(request.idempotency_key, fingerprint)
        if cached is not None:
            return cached
        old, frontmatter, body = _read_existing(self.vault_root, request.plan_path)
        actual_hash = content_hash(old)
        if actual_hash != request.expected_hash:
            raise DailyInteractionError("stale_write", "The plan changed after it was read.", "Reload the plan and retry.")
        history = frontmatter.get("execution_history")
        if not isinstance(history, list):
            raise DailyInteractionError("invalid_execution_history", "Execution history must be a list.", "Repair the plan note.")
        source = next((item for item in history if isinstance(item, dict) and item.get("event_id") == request.corrects_event_id), None)
        if source is None:
            raise DailyInteractionError("event_not_found", "The execution event no longer exists.", "Reload execution history.")
        task_id = source.get("task_id")
        if not isinstance(task_id, str):
            raise DailyInteractionError("invalid_execution_history", "The source event has no valid task ID.", "Repair the source event.")
        event: dict[str, Any] = {
            "schema_version": 1,
            "event_id": request.idempotency_key,
            "task_id": task_id,
            "outcome": request.outcome,
            "date": request.day,
            "actor": self.actor_id,
            "corrects_event_id": request.corrects_event_id,
        }
        if request.actual_minutes is not None:
            event["actual_minutes"] = request.actual_minutes
        if request.completion_fraction is not None:
            event["completion_fraction"] = request.completion_fraction
        if request.reason:
            event["reason"] = request.reason.strip()
        history.append(event)
        document = _frontmatter_document(frontmatter, body)
        _atomic_write(self.vault_root, request.plan_path, document, expected_hash=actual_hash, create=False)
        result = {"plan_path": request.plan_path, "content_hash": content_hash(document), "event_id": request.idempotency_key, "corrects_event_id": request.corrects_event_id}
        self._cache(request.idempotency_key, fingerprint, result)
        return result

    def reset_derived(self) -> tuple[str, ...]:
        root = self.runtime_dir / "feedback"
        removed: list[str] = []
        if root.exists():
            for path in sorted(root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                    removed.append(str(path.relative_to(self.runtime_dir)))
                elif path.is_dir():
                    try:
                        path.rmdir()
                    except OSError:
                        pass
        return tuple(sorted(removed))
