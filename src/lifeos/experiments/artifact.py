"""Canonical Markdown persistence and lifecycle mutations for experiments."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import yaml

from lifeos.daily.service import _atomic_write, content_hash
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, iter_vault_markdown, read_vault_markdown

from .contracts import (
    ExperimentArtifact,
    ExperimentError,
    ExperimentMetadata,
    ExperimentProtocol,
    ExperimentState,
    LifecycleEvent,
    Observation,
    ProtocolAmendment,
    SafetyClassification,
    SourceReference,
    metadata_from_dict,
    validate_transition,
)

_MANAGED_START = "<!-- lifeos:managed:start personal-experiment -->"
_MANAGED_END = "<!-- lifeos:managed:end personal-experiment -->"
_MANAGED_RE = re.compile(re.escape(_MANAGED_START) + r".*?" + re.escape(_MANAGED_END), re.S)
_ID_RE = re.compile(r"^exp-(\d{8}T\d{6}Z)-[a-f0-9]{8}$")


def utc_now(value: datetime | None = None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ExperimentError("invalid_timestamp", "Experiment timestamps must include a timezone.")
    return moment.astimezone(timezone.utc)


def protocol_hash(protocol: ExperimentProtocol) -> str:
    dumped = yaml.safe_dump(protocol.to_dict(), sort_keys=True, allow_unicode=True)
    return "sha256:" + hashlib.sha256(dumped.encode()).hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:64] or "experiment"


def _experiment_id(moment: datetime) -> str:
    return f"exp-{moment.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"


def _path(metadata: ExperimentMetadata) -> str:
    match = _ID_RE.fullmatch(metadata.experiment_id)
    if match is None:
        raise ExperimentError("invalid_experiment", "Experiment ID is malformed.")
    return f"experiments/{match.group(1)[:4]}/{_slug(metadata.title)}-{metadata.experiment_id}.md"


def _render_managed(metadata: ExperimentMetadata) -> str:
    protocol = metadata.protocol
    lines = [
        _MANAGED_START,
        "# Experiment protocol",
        "",
        f"**State:** `{metadata.state}`  ",
        f"**Safety:** `{metadata.safety.level}`  ",
        f"**Question:** {protocol.question}  ",
        f"**Hypothesis:** {protocol.hypothesis}  ",
        f"**Intervention:** {protocol.intervention}",
        "",
        "## Measures",
        "",
    ]
    if protocol.outcome_measures:
        for measure in protocol.outcome_measures:
            unit = f" ({measure.unit})" if measure.unit else ""
            lines.append(
                f"- `{measure.measure_id}` {measure.display_name}{unit}: {measure.kind}, {measure.role}, {measure.cadence}"
            )
    else:
        lines.append("- No measures defined.")
    lines.extend(["", "## Phases", ""])
    for phase in protocol.phases:
        lines.append(
            f"- `{phase.phase_id}` {phase.name}: {phase.start_date} to {phase.end_date} ({phase.kind})"
        )
    if not protocol.phases:
        lines.append("- No phases defined.")
    lines.extend(["", "## Observations", ""])
    for observation in metadata.observations[-30:]:
        rendered = repr(observation.value) if observation.state == "measured" else observation.state
        lines.append(
            f"- {observation.observed_at} · `{observation.measure_id}` · `{observation.phase_id}` · {rendered}"
        )
    if not metadata.observations:
        lines.append("- No observations recorded.")
    lines.extend(["", "## Amendments", ""])
    for amendment in metadata.amendments:
        lines.append(
            f"- {amendment.created_at} · **{amendment.reason}**: {'; '.join(amendment.changes)}"
        )
    if not metadata.amendments:
        lines.append("- No protocol amendments.")
    if metadata.analyses:
        latest = metadata.analyses[-1]
        lines.extend(
            [
                "",
                "## Latest analysis",
                "",
                f"- Status: `{latest.status}`",
                f"- Evidence: `{latest.evidence_kind}`",
            ]
        )
        for summary in latest.summaries:
            lines.append(
                f"- {summary.get('label', summary.get('measure_id', 'Summary'))}: {summary.get('text', summary)}"
            )
    lines.append(_MANAGED_END)
    return "\n".join(lines)


def _document(metadata: ExperimentMetadata, human_body: str) -> str:
    dumped = yaml.safe_dump(metadata.to_frontmatter(), sort_keys=False, allow_unicode=True).rstrip()
    human = human_body.strip("\n") or "## User annotations\n\n"
    return f"---\n{dumped}\n---\n\n{_render_managed(metadata)}\n\n{human}\n"


def parse_experiment(path: Path, relative_path: str, content: str) -> ExperimentArtifact:
    parsed = parse_markdown_note(path, content=content)
    error = next((item for item in parsed.findings if item.severity == "error"), None)
    if error is not None:
        raise ExperimentError("malformed_artifact", error.message, {"path": relative_path})
    frontmatter = dict(parsed.frontmatter)
    if frontmatter.get("type") != "personal-experiment":
        raise ExperimentError("unsupported_artifact", "The note is not a personal experiment.")
    matches = list(_MANAGED_RE.finditer(parsed.body))
    if len(matches) != 1:
        raise ExperimentError(
            "malformed_artifact", "The managed experiment block must appear exactly once."
        )
    match = matches[0]
    human_body = (parsed.body[: match.start()] + parsed.body[match.end() :]).strip("\n") + "\n"
    metadata = metadata_from_dict(frontmatter)
    return ExperimentArtifact(
        relative_path, "sha256:" + content_hash(content), metadata, human_body
    )


class ExperimentArtifactService:
    def __init__(self, *, vault_root: Path, runtime_dir: Path) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir

    def create(
        self,
        *,
        title: str,
        description: str,
        category: str,
        protocol: ExperimentProtocol,
        origins: tuple[SourceReference, ...] = (),
        safety: SafetyClassification = SafetyClassification(),
        now: datetime | None = None,
        parent_experiment_id: str | None = None,
        repeated_from_experiment_id: str | None = None,
    ) -> ExperimentArtifact:
        moment = utc_now(now)
        experiment_id = _experiment_id(moment)
        initial = LifecycleEvent(
            f"life-{secrets.token_hex(6)}", None, "idea", moment.isoformat(), "created"
        )
        metadata = ExperimentMetadata(
            experiment_id=experiment_id,
            title=title.strip(),
            description=description.strip(),
            state="idea",
            category=category.strip() or "other",
            created_at=moment.isoformat(),
            updated_at=moment.isoformat(),
            protocol=protocol,
            safety=safety,
            origins=origins,
            lifecycle=(initial,),
            parent_experiment_id=parent_experiment_id,
            repeated_from_experiment_id=repeated_from_experiment_id,
        )
        relative_path = _path(metadata)
        _atomic_write(
            self.vault_root,
            relative_path,
            _document(metadata, "## User annotations\n\n"),
            expected_hash=None,
            create=True,
        )
        return self.load(relative_path)

    def create_imported(self, metadata: ExperimentMetadata, human_body: str) -> ExperimentArtifact:
        """Create one canonical artifact from a validated migration preview."""
        relative_path = _path(metadata)
        _atomic_write(
            self.vault_root,
            relative_path,
            _document(metadata, human_body),
            expected_hash=None,
            create=True,
        )
        return self.load(relative_path)

    def load(self, relative_path: str) -> ExperimentArtifact:
        try:
            source = read_vault_markdown(self.vault_root, relative_path)
        except VaultAccessError as exc:
            raise ExperimentError(exc.code, str(exc), {"path": relative_path}) from exc
        return parse_experiment(source.path, source.relative_path, source.content)

    def list(self, *, states: frozenset[str] | None = None) -> tuple[ExperimentArtifact, ...]:
        try:
            sources = iter_vault_markdown(self.vault_root, roots=("experiments",))
        except VaultAccessError as exc:
            if exc.code == "not-found":
                return ()
            raise ExperimentError(exc.code, str(exc)) from exc
        artifacts = tuple(
            parse_experiment(item.path, item.relative_path, item.content) for item in sources
        )
        selected = (
            artifacts
            if states is None
            else tuple(item for item in artifacts if item.metadata.state in states)
        )
        return tuple(
            sorted(
                selected,
                key=lambda item: (item.metadata.updated_at, item.metadata.experiment_id),
                reverse=True,
            )
        )

    def find(self, experiment_id: str) -> ExperimentArtifact:
        matches = [item for item in self.list() if item.metadata.experiment_id == experiment_id]
        if len(matches) != 1:
            raise ExperimentError(
                "not_found" if not matches else "duplicate_identity",
                "Experiment could not be resolved uniquely.",
                {"experiment_id": experiment_id, "count": len(matches)},
            )
        return matches[0]

    def save(
        self, artifact: ExperimentArtifact, metadata: ExperimentMetadata, *, expected_hash: str
    ) -> ExperimentArtifact:
        current = self.load(artifact.path)
        if current.content_hash != expected_hash:
            raise ExperimentError(
                "stale_artifact",
                "Experiment changed after it was opened.",
                {"actual_hash": current.content_hash},
            )
        _atomic_write(
            self.vault_root,
            artifact.path,
            _document(metadata, current.human_body),
            expected_hash=expected_hash.removeprefix("sha256:"),
            create=False,
        )
        return self.load(artifact.path)

    def transition(
        self,
        relative_path: str,
        target: ExperimentState,
        *,
        expected_hash: str,
        reason: str = "",
        now: datetime | None = None,
    ) -> ExperimentArtifact:
        artifact = self.load(relative_path)
        validate_transition(artifact.metadata.state, target)
        if (
            target in {"baseline", "scheduled", "active"}
            and not artifact.metadata.safety.allows_activation
        ):
            raise ExperimentError(
                "unsafe_experiment",
                "Safety classification prevents baseline collection, scheduling, or activation.",
                artifact.metadata.safety.to_dict(),
            )
        moment = utc_now(now)
        event = LifecycleEvent(
            f"life-{secrets.token_hex(6)}",
            artifact.metadata.state,
            target,
            moment.isoformat(),
            reason.strip(),
        )
        metadata = replace(
            artifact.metadata,
            state=target,
            updated_at=moment.isoformat(),
            lifecycle=(*artifact.metadata.lifecycle, event),
        )
        return self.save(artifact, metadata, expected_hash=expected_hash)

    def update_protocol(
        self,
        relative_path: str,
        protocol: ExperimentProtocol,
        *,
        expected_hash: str,
        now: datetime | None = None,
    ) -> ExperimentArtifact:
        artifact = self.load(relative_path)
        if artifact.metadata.state not in {"idea", "drafting"}:
            raise ExperimentError(
                "amendment_required",
                "Material protocol changes after drafting require a dated amendment.",
                {"state": artifact.metadata.state},
            )
        moment = utc_now(now)
        from .safety import classify_safety

        return self.save(
            artifact,
            replace(
                artifact.metadata,
                protocol=protocol,
                safety=classify_safety(protocol),
                updated_at=moment.isoformat(),
            ),
            expected_hash=expected_hash,
        )

    def amend_protocol(
        self,
        relative_path: str,
        protocol: ExperimentProtocol,
        *,
        reason: str,
        changes: tuple[str, ...],
        expected_hash: str,
        now: datetime | None = None,
    ) -> ExperimentArtifact:
        artifact = self.load(relative_path)
        if artifact.metadata.state in {"idea", "drafting"}:
            raise ExperimentError(
                "amendment_not_required", "Edit the draft protocol directly before baseline begins."
            )
        moment = utc_now(now)
        amendment = ProtocolAmendment(
            f"amend-{secrets.token_hex(6)}",
            moment.isoformat(),
            reason.strip(),
            changes,
            protocol_hash(artifact.metadata.protocol),
        )
        metadata = replace(
            artifact.metadata,
            protocol=protocol,
            safety=__import__(
                "lifeos.experiments.safety", fromlist=["classify_safety"]
            ).classify_safety(protocol),
            amendments=(*artifact.metadata.amendments, amendment),
            updated_at=moment.isoformat(),
        )
        return self.save(artifact, metadata, expected_hash=expected_hash)

    def append_observation(
        self,
        relative_path: str,
        observation: Observation,
        *,
        expected_hash: str,
        now: datetime | None = None,
    ) -> ExperimentArtifact:
        artifact = self.load(relative_path)
        if any(
            item.observation_id == observation.observation_id
            for item in artifact.metadata.observations
        ):
            raise ExperimentError("duplicate_observation", "Observation identity already exists.")
        moment = utc_now(now)
        metadata = replace(
            artifact.metadata,
            observations=(*artifact.metadata.observations, observation),
            updated_at=moment.isoformat(),
        )
        return self.save(artifact, metadata, expected_hash=expected_hash)

    def clone(
        self, relative_path: str, *, title: str | None = None, now: datetime | None = None
    ) -> ExperimentArtifact:
        original = self.load(relative_path)
        return self.create(
            title=title or f"{original.metadata.title} repeat",
            description=original.metadata.description,
            category=original.metadata.category,
            protocol=original.metadata.protocol,
            origins=(SourceReference(original.path, "cloned-from", original.content_hash),),
            safety=original.metadata.safety,
            now=now,
            parent_experiment_id=original.metadata.parent_experiment_id
            or original.metadata.experiment_id,
            repeated_from_experiment_id=original.metadata.experiment_id,
        )
