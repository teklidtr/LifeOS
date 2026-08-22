"""Proposal-gated follow-up actions from experiment evidence."""

from __future__ import annotations

import difflib
import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from lifeos._atomic_write import AtomicWriteError, atomic_write_file_secure
from lifeos.daily.service import content_hash
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.patches import (
    CreateFile,
    PatchDocumentV2,
    PatchHumanFile,
    serialize_patch_json_bytes,
)
from lifeos.proposals.schema import (
    ProposalMetadata,
    ProposalRisk,
    ProposalStatus,
    generate_proposal_id,
)
from lifeos.proposals.review_snapshot import build_review_snapshot_bytes_from_patches
from lifeos.vault import VaultAccessError, read_vault_markdown

from .artifact import ExperimentArtifactService
from .contracts import ExperimentError

ExperimentProposalAction = Literal[
    "adopt-behavior",
    "reject-behavior",
    "extend-experiment",
    "repeat-experiment",
    "follow-up-experiment",
    "update-goal-or-plan",
    "create-or-modify-habit",
    "create-tasks",
    "create-knowledge-note",
    "append-knowledge-finding",
    "create-research-question",
    "add-weekly-review-insight",
]


@dataclass(frozen=True, slots=True)
class ExperimentProposalRequest:
    experiment_path: str
    action: ExperimentProposalAction
    target_path: str
    content: str
    create_target: bool
    included_actions: tuple[str, ...] = ()
    excluded_actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExperimentProposalPreview:
    proposal_id: str
    action: str
    target_path: str
    operation: str
    base_hash: str | None
    unified_diff: str | None
    new_content: str | None
    source_experiment_id: str
    source_experiment_hash: str
    analysis_id: str | None
    analysis_limitations: tuple[str, ...]
    included_actions: tuple[str, ...]
    excluded_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "action": self.action,
            "target_path": self.target_path,
            "operation": self.operation,
            "base_hash": self.base_hash,
            "unified_diff": self.unified_diff,
            "new_content": self.new_content,
            "source_experiment_id": self.source_experiment_id,
            "source_experiment_hash": self.source_experiment_hash,
            "analysis_id": self.analysis_id,
            "analysis_limitations": list(self.analysis_limitations),
            "included_actions": list(self.included_actions),
            "excluded_actions": list(self.excluded_actions),
        }


class ExperimentProposalService:
    def __init__(self, *, vault_root: Path, runtime_dir: Path, actor_id: str) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.actor_id = actor_id
        self.artifacts = ExperimentArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)

    def preview(
        self, request: ExperimentProposalRequest, *, now: datetime | None = None
    ) -> tuple[ExperimentProposalPreview, PatchDocumentV2, bytes]:
        artifact = self.artifacts.load(request.experiment_path)
        body = request.content.strip()
        if not body:
            raise ExperimentError(
                "empty_proposal", "Experiment proposal content must not be blank."
            )
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            raise ExperimentError(
                "invalid_timestamp", "Proposal timestamp must include a timezone."
            )
        moment = moment.astimezone(timezone.utc)
        fingerprint = "\0".join(
            (
                artifact.metadata.experiment_id,
                artifact.content_hash,
                request.action,
                request.target_path,
                body,
            )
        )
        suffix = hashlib.sha256(fingerprint.encode()).hexdigest()[:8]
        proposal_id = generate_proposal_id(lambda: moment, lambda: suffix)
        base_hash: str | None = None
        unified_diff: str | None = None
        operation: CreateFile | PatchHumanFile
        if request.create_target:
            if (self.vault_root / request.target_path).exists():
                raise ExperimentError("target_exists", "The proposed target already exists.")
            candidate = body.rstrip() + "\n"
            operation = CreateFile("op-experiment-create", request.target_path, "absent", candidate)
            operation_name = "create_file"
            new_content: str | None = candidate
        else:
            try:
                source = read_vault_markdown(self.vault_root, request.target_path)
            except VaultAccessError as exc:
                raise ExperimentError(
                    exc.code, str(exc), {"target_path": request.target_path}
                ) from exc
            candidate = source.content.rstrip() + "\n\n" + body + "\n"
            base_hash = "sha256:" + content_hash(source.content)
            diff = tuple(
                difflib.unified_diff(
                    source.content.splitlines(keepends=True),
                    candidate.splitlines(keepends=True),
                    fromfile=request.target_path,
                    tofile=request.target_path,
                )
            )
            unified_diff = "".join(diff[2:])
            operation = PatchHumanFile(
                "op-experiment-append", request.target_path, base_hash, unified_diff
            )
            operation_name = "patch_human_file"
            new_content = None
        patch = PatchDocumentV2(2, proposal_id, (operation,))
        latest = artifact.metadata.analyses[-1] if artifact.metadata.analyses else None
        limitations = (
            latest.limitations
            if latest
            else (
                "No saved analysis is attached; review raw observations before applying this action.",
            )
        )
        timestamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        metadata = ProposalMetadata(
            id=proposal_id,
            schema_version=1,
            patch_schema_version=2,
            lifecycle_schema_version=1,
            title=f"Experiment follow-up: {request.action}",
            description=f"Reviewed follow-up from {artifact.metadata.title}",
            status=ProposalStatus.DRAFT,
            risk=ProposalRisk.MEDIUM,
            created_at=timestamp,
            created_by=self.actor_id,
            submitted_at=None,
            submitted_by=None,
            review_digest=None,
            approved_at=None,
            approved_by=None,
            rejected_at=None,
            rejected_by=None,
            rejection_reason=None,
            applied_at=None,
            applied_by=None,
            related_goals=(),
            related_sources=(artifact.path,),
            extensions={
                "personal_experiment": {
                    "experiment_id": artifact.metadata.experiment_id,
                    "experiment_hash": artifact.content_hash,
                    "analysis_id": latest.analysis_id if latest else None,
                    "action": request.action,
                    "target_path": request.target_path,
                    "included_actions": list(request.included_actions),
                    "excluded_actions": list(request.excluded_actions),
                    "limitations": list(limitations),
                }
            },
        )
        proposal_body = "\n".join(
            [
                "## Experiment evidence",
                "",
                f"- Experiment: `{artifact.metadata.experiment_id}`",
                f"- Source: `{artifact.path}` at `{artifact.content_hash}`",
                f"- Analysis: `{latest.analysis_id if latest else 'none'}`",
                f"- Conclusion: `{artifact.metadata.conclusion or 'not-recorded'}`",
                "",
                "## Limitations",
                "",
                *[f"- {item}" for item in limitations],
                "",
                "## Proposed action",
                "",
                f"- Action: `{request.action}`",
                f"- Target: `{request.target_path}`",
                f"- Operation: `{operation_name}`",
                f"- Included: {', '.join(request.included_actions) or 'none listed'}",
                f"- Excluded: {', '.join(request.excluded_actions) or 'none listed'}",
                "",
                "```markdown",
                body,
                "```",
                "",
                "The experiment result does not alter any external canonical artifact until this proposal is reviewed, approved, and applied.",
            ]
        )
        proposal_markdown = serialize_proposal_markdown(metadata, proposal_body)
        preview = ExperimentProposalPreview(
            proposal_id,
            request.action,
            request.target_path,
            operation_name,
            base_hash,
            unified_diff,
            new_content,
            artifact.metadata.experiment_id,
            artifact.content_hash,
            latest.analysis_id if latest else None,
            limitations,
            request.included_actions,
            request.excluded_actions,
        )
        return preview, patch, proposal_markdown

    def publish(
        self, request: ExperimentProposalRequest, *, now: datetime | None = None
    ) -> dict[str, object]:
        preview, patch, proposal_markdown = self.preview(request, now=now)
        root = self.vault_root / "proposals"
        target = root / preview.proposal_id
        patches_json = serialize_patch_json_bytes(patch)
        review_json = build_review_snapshot_bytes_from_patches(
            vault_root=self.vault_root,
            patches_json=patches_json,
        )
        root.mkdir(parents=True, exist_ok=True)
        created = False
        published = False
        fd = -1
        try:
            target.mkdir(exist_ok=False)
            created = True
            fd = os.open(
                target, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            )
            atomic_write_file_secure(fd, "proposal.md", proposal_markdown)
            atomic_write_file_secure(fd, "patches.json", patches_json)
            atomic_write_file_secure(fd, "review.json", review_json)
            published = True
        except FileExistsError as exc:
            raise ExperimentError(
                "proposal_exists", "Equivalent experiment proposal already exists."
            ) from exc
        except (OSError, AtomicWriteError) as exc:
            raise ExperimentError("proposal_publish_failed", str(exc)) from exc
        finally:
            if fd >= 0:
                os.close(fd)
            if created and not published:
                shutil.rmtree(target, ignore_errors=True)
        return {
            "proposal_id": preview.proposal_id,
            "proposal_path": f"proposals/{preview.proposal_id}",
            "preview": preview.to_dict(),
        }
