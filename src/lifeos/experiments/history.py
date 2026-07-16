"""Rebuildable experiment index, lineage, and recovery diagnostics."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from lifeos.vault import VaultAccessError, iter_vault_markdown

from .artifact import parse_experiment
from .contracts import ExperimentError


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
    entries: list[ExperimentIndexEntry] = []
    diagnostics: list[dict[str, object]] = []
    seen: dict[str, str] = {}
    processed = 0
    for source in sources:
        try:
            artifact = parse_experiment(source.path, source.relative_path, source.content)
        except ExperimentError as exc:
            diagnostics.append(
                {"code": exc.code, "path": source.relative_path, "message": exc.message}
            )
            continue
        identity = artifact.metadata.experiment_id
        if identity in seen:
            diagnostics.append(
                {
                    "code": "duplicate_identity",
                    "experiment_id": identity,
                    "paths": [seen[identity], artifact.path],
                }
            )
            continue
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
                tuple(item.measure_id for item in artifact.metadata.protocol.outcome_measures),
            )
        )
        processed += 1
        if processed % batch_size == 0:
            checkpoint.write_text(
                json.dumps({"processed": processed, "last_path": artifact.path}, sort_keys=True)
                + "\n"
            )
        if interrupt_after is not None and processed >= interrupt_after:
            checkpoint.write_text(
                json.dumps(
                    {"processed": processed, "last_path": artifact.path, "interrupted": True},
                    sort_keys=True,
                )
                + "\n"
            )
            return ExperimentIndexReport(
                "interrupted", tuple(entries), tuple(diagnostics), str(checkpoint)
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
    checkpoint.unlink(missing_ok=True)
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
