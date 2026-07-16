"""Recovery audit for canonical experiment artifacts and disposable indexes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, iter_vault_markdown

from .artifact import parse_experiment
from .contracts import ExperimentArtifact, ExperimentError
from .history import ExperimentIndexReport, load_experiment_index, rebuild_experiment_index


@dataclass(frozen=True, slots=True)
class ExperimentRecoveryReport:
    state: str
    index: ExperimentIndexReport
    diagnostics: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "index": self.index.to_dict(),
            "diagnostics": [dict(item) for item in self.diagnostics],
        }


def audit_experiment_recovery(
    *,
    vault_root: Path,
    runtime_dir: Path,
    rebuild: bool = False,
    interrupt_after: int | None = None,
) -> ExperimentRecoveryReport:
    previous = load_experiment_index(runtime_dir=runtime_dir)
    diagnostics: list[dict[str, object]] = []
    artifacts: dict[str, ExperimentArtifact] = {}
    paths: set[str] = set()
    try:
        sources = iter_vault_markdown(vault_root, roots=("experiments",))
    except VaultAccessError as exc:
        if exc.code == "not-found":
            sources = ()
        else:
            raise ExperimentError(exc.code, str(exc)) from exc
    for source in sources:
        parsed = parse_markdown_note(source.path, content=source.content)
        if parsed.frontmatter.get("type") != "personal-experiment":
            continue
        try:
            artifact = parse_experiment(source.path, source.relative_path, source.content)
        except ExperimentError as exc:
            diagnostics.append(
                {"code": exc.code, "path": source.relative_path, "message": exc.message}
            )
            continue
        identity = artifact.metadata.experiment_id
        if identity in artifacts:
            earlier = artifacts[identity]
            diagnostics.append(
                {
                    "code": "duplicate_identity",
                    "experiment_id": identity,
                    "paths": [earlier.path, artifact.path],
                }
            )
            continue
        artifacts[identity] = artifact
        paths.add(artifact.path)
    for artifact in artifacts.values():
        references = [
            *artifact.metadata.origins,
            *artifact.metadata.source_refs,
            *(
                ref
                for observation in artifact.metadata.observations
                for ref in observation.source_refs
            ),
        ]
        for ref in references:
            if not (vault_root / ref.path).exists():
                diagnostics.append(
                    {
                        "code": "missing_linked_source",
                        "experiment_id": artifact.metadata.experiment_id,
                        "experiment_path": artifact.path,
                        "source_path": ref.path,
                        "relation": ref.relation,
                    }
                )
    previous_by_id = {item.experiment_id: item for item in previous.entries}
    current_by_id = {identity: artifact for identity, artifact in artifacts.items()}
    for identity, old in previous_by_id.items():
        current = current_by_id.get(identity)
        if current is None:
            diagnostics.append(
                {"code": "deleted_artifact", "experiment_id": identity, "previous_path": old.path}
            )
        elif current.path != old.path:
            diagnostics.append(
                {
                    "code": "moved_artifact",
                    "experiment_id": identity,
                    "previous_path": old.path,
                    "current_path": current.path,
                }
            )
    # Observation notes are optional external sources. Orphans remain visible rather than silently discarded.
    try:
        observation_sources = iter_vault_markdown(vault_root, roots=("observations",))
    except VaultAccessError:
        observation_sources = ()
    for source in observation_sources:
        parsed = parse_markdown_note(source.path, content=source.content)
        if parsed.frontmatter.get("type") != "experiment-observation":
            continue
        identity = str(parsed.frontmatter.get("experiment_id", ""))
        if not identity or identity not in artifacts:
            diagnostics.append(
                {
                    "code": "orphaned_observation",
                    "path": source.relative_path,
                    "experiment_id": identity or None,
                }
            )
    index = (
        rebuild_experiment_index(
            vault_root=vault_root, runtime_dir=runtime_dir, interrupt_after=interrupt_after
        )
        if rebuild
        else previous
    )
    state = (
        "interrupted"
        if index.state == "interrupted"
        else "attention"
        if diagnostics
        else index.state
    )
    return ExperimentRecoveryReport(state, index, tuple(diagnostics))
