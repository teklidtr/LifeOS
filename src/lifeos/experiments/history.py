"""Rebuildable experiment index, lineage, and recovery diagnostics."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from lifeos.vault import VaultAccessError, VaultMarkdownFile, iter_vault_markdown

from .artifact import parse_experiment
from .contracts import ExperimentError

_CHECKPOINT_SCHEMA = 2


@dataclass(frozen=True, slots=True)
class ExperimentIndexEntry:
    experiment_id: str
    path: str
    content_hash: str
    title: str
    state: str
    category: str
    updated_at: str
    conclusion: str | None
    parent_experiment_id: str | None
    repeated_from_experiment_id: str | None
    measure_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "measure_ids": list(self.measure_ids)}


@dataclass(frozen=True, slots=True)
class ExperimentIndexReport:
    state: str
    entries: tuple[ExperimentIndexEntry, ...]
    diagnostics: tuple[dict[str, object], ...]
    checkpoint_path: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "entries": [item.to_dict() for item in self.entries],
            "diagnostics": [dict(item) for item in self.diagnostics],
            "checkpoint_path": self.checkpoint_path,
        }


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


def _checkpoint_entry(raw: object) -> ExperimentIndexEntry:
    if not isinstance(raw, dict):
        raise ValueError("Checkpoint entry must be an object.")
    required_strings = (
        "experiment_id",
        "path",
        "content_hash",
        "title",
        "state",
        "category",
        "updated_at",
    )
    values: dict[str, str] = {}
    for field in required_strings:
        value = raw.get(field)
        if not isinstance(value, str):
            raise ValueError(f"Checkpoint entry field {field} must be a string.")
        values[field] = value

    optional_strings: dict[str, str | None] = {}
    for field in ("conclusion", "parent_experiment_id", "repeated_from_experiment_id"):
        value = raw.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Checkpoint entry field {field} must be a string or null.")
        optional_strings[field] = value

    measure_ids = raw.get("measure_ids")
    if not isinstance(measure_ids, list) or any(
        not isinstance(value, str) for value in measure_ids
    ):
        raise ValueError("Checkpoint entry measure_ids must be strings.")

    return ExperimentIndexEntry(
        values["experiment_id"],
        values["path"],
        values["content_hash"],
        values["title"],
        values["state"],
        values["category"],
        values["updated_at"],
        optional_strings["conclusion"],
        optional_strings["parent_experiment_id"],
        optional_strings["repeated_from_experiment_id"],
        tuple(measure_ids),
    )


def _discard_checkpoint(checkpoint: Path) -> None:
    checkpoint.unlink(missing_ok=True)
    checkpoint.with_suffix(".tmp").unlink(missing_ok=True)


def _load_rebuild_checkpoint(
    *, checkpoint: Path, sources: tuple[VaultMarkdownFile, ...], source_signature: str
) -> tuple[int, list[ExperimentIndexEntry], list[dict[str, object]]]:
    if not checkpoint.exists():
        return 0, [], []
    try:
        raw = json.loads(checkpoint.read_text())
        if not isinstance(raw, dict) or raw.get("schema") != _CHECKPOINT_SCHEMA:
            raise ValueError("Unsupported experiment rebuild checkpoint schema.")
        checkpoint_digest = raw.get("checkpoint_digest")
        unsigned = {key: value for key, value in raw.items() if key != "checkpoint_digest"}
        if (
            not isinstance(checkpoint_digest, str)
            or checkpoint_digest != _checkpoint_digest(unsigned)
        ):
            raise ValueError("Experiment rebuild checkpoint integrity is invalid.")
        if raw.get("source_signature") != source_signature or raw.get("source_count") != len(
            sources
        ):
            raise ValueError("Experiment rebuild checkpoint sources changed.")
        next_index = raw.get("next_index")
        raw_entries = raw.get("entries")
        raw_diagnostics = raw.get("diagnostics")
        if (
            type(next_index) is not int
            or not 0 <= next_index <= len(sources)
            or not isinstance(raw_entries, list)
            or not isinstance(raw_diagnostics, list)
        ):
            raise ValueError("Experiment rebuild checkpoint shape is invalid.")
        entries = [_checkpoint_entry(item) for item in raw_entries]
        diagnostics: list[dict[str, object]] = []
        for item in raw_diagnostics:
            if not isinstance(item, dict) or not isinstance(item.get("code"), str):
                raise ValueError("Experiment rebuild checkpoint diagnostic is invalid.")
            diagnostics.append(dict(item))
        processed_sources = {
            source.relative_path: "sha256:" + hashlib.sha256(source.content_bytes).hexdigest()
            for source in sources[:next_index]
        }
        if any(processed_sources.get(entry.path) != entry.content_hash for entry in entries):
            raise ValueError(
                "Experiment rebuild checkpoint entries do not match processed sources."
            )
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
    entries: list[ExperimentIndexEntry],
    diagnostics: list[dict[str, object]],
) -> None:
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
    temp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    os.replace(temp, checkpoint)


def rebuild_experiment_index(
    *,
    vault_root: Path,
    runtime_dir: Path,
    batch_size: int = 100,
    interrupt_after: int | None = None,
) -> ExperimentIndexReport:
    if batch_size < 1:
        raise ExperimentError(
            "invalid_batch_size", "Experiment rebuild batch size must be positive."
        )
    index_dir = runtime_dir / "experiments"
    index_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = index_dir / "rebuild-checkpoint.json"
    output_path = index_dir / "index.json"
    try:
        sources = iter_vault_markdown(vault_root, roots=("experiments",))
    except VaultAccessError as exc:
        if exc.code == "not-found":
            sources = ()
        else:
            raise ExperimentError(exc.code, str(exc)) from exc

    source_signature = _source_signature(sources)
    next_index, entries, diagnostics = _load_rebuild_checkpoint(
        checkpoint=checkpoint,
        sources=sources,
        source_signature=source_signature,
    )
    seen: dict[str, str] = {}
    for entry in entries:
        seen.setdefault(entry.experiment_id, entry.path)

    processed_this_run = 0
    for source_index in range(next_index, len(sources)):
        source = sources[source_index]
        try:
            artifact = parse_experiment(source.path, source.relative_path, source.content)
        except ExperimentError as exc:
            diagnostics.append(
                {"code": exc.code, "path": source.relative_path, "message": exc.message}
            )
        else:
            identity = artifact.metadata.experiment_id
            if identity in seen:
                diagnostics.append(
                    {
                        "code": "duplicate_identity",
                        "experiment_id": identity,
                        "paths": [seen[identity], artifact.path],
                    }
                )
            else:
                seen[identity] = artifact.path
                entries.append(
                    ExperimentIndexEntry(
                        identity,
                        artifact.path,
                        artifact.content_hash,
                        artifact.metadata.title,
                        artifact.metadata.state,
                        artifact.metadata.category,
                        artifact.metadata.updated_at,
                        artifact.metadata.conclusion,
                        artifact.metadata.parent_experiment_id,
                        artifact.metadata.repeated_from_experiment_id,
                        tuple(
                            item.measure_id
                            for item in artifact.metadata.protocol.outcome_measures
                        ),
                    )
                )

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
            return ExperimentIndexReport(
                "interrupted", tuple(entries), tuple(diagnostics), str(checkpoint)
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

    entries.sort(key=lambda item: (item.updated_at, item.experiment_id), reverse=True)
    payload = {
        "schema": 1,
        "entries": [item.to_dict() for item in entries],
        "diagnostics": diagnostics,
    }
    temp = output_path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    os.replace(temp, output_path)
    _discard_checkpoint(checkpoint)
    return ExperimentIndexReport("ready", tuple(entries), tuple(diagnostics))


def load_experiment_index(*, runtime_dir: Path) -> ExperimentIndexReport:
    path = runtime_dir / "experiments" / "index.json"
    if not path.exists():
        return ExperimentIndexReport(
            "missing-index",
            (),
            ({"code": "rebuild_required", "message": "Experiment index is missing."},),
        )
    try:
        data = json.loads(path.read_text())
        entries = tuple(
            ExperimentIndexEntry(
                str(item["experiment_id"]),
                str(item["path"]),
                str(item["content_hash"]),
                str(item["title"]),
                str(item["state"]),
                str(item["category"]),
                str(item["updated_at"]),
                str(item["conclusion"]) if item.get("conclusion") else None,
                str(item["parent_experiment_id"]) if item.get("parent_experiment_id") else None,
                str(item["repeated_from_experiment_id"])
                if item.get("repeated_from_experiment_id")
                else None,
                tuple(str(value) for value in item.get("measure_ids", ())),
            )
            for item in data.get("entries", ())
        )
        return ExperimentIndexReport(
            "ready", entries, tuple(dict(item) for item in data.get("diagnostics", ()))
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        return ExperimentIndexReport(
            "corrupt-index", (), ({"code": "rebuild_required", "message": str(exc)},)
        )


def compare_experiments(
    entries: Iterable[ExperimentIndexEntry], left_id: str, right_id: str
) -> dict[str, object]:
    indexed = {item.experiment_id: item for item in entries}
    left = indexed.get(left_id)
    right = indexed.get(right_id)
    if left is None or right is None:
        raise ExperimentError("not_found", "Both experiments are required for comparison.")
    compatible = bool(set(left.measure_ids) & set(right.measure_ids))
    return {
        "left": left.to_dict(),
        "right": right.to_dict(),
        "compatible": compatible,
        "warning": None
        if compatible
        else "The experiments do not share a measure identity; results must not be combined.",
    }
