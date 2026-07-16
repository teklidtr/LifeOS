"""Proposal-gated follow-up actions sourced from rich captures."""

from __future__ import annotations

import difflib
import hashlib
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from lifeos._atomic_write import AtomicWriteError, atomic_write_file_secure
from lifeos.daily.service import content_hash
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.patches import (
    CreateFile,
    PatchDocumentV2,
    PatchHumanFile,
    PatchOperationV2,
    serialize_patch_json_bytes,
)
from lifeos.proposals.schema import (
    ProposalMetadata,
    ProposalRisk,
    ProposalStatus,
    generate_proposal_id,
)
from lifeos.vault import VaultAccessError, read_vault_markdown

from .artifact import CaptureArtifactService
from .contracts import CaptureError


@dataclass(frozen=True, slots=True)
class CaptureProposalRequest:
    capture_path: str
    action: str
    target_path: str
    content: str
    create_target: bool = False
    attachment_ids: tuple[str, ...] = ()
    included_actions: tuple[str, ...] = ()
    excluded_actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaptureProposalPreview:
    proposal_id: str
    target_path: str
    operation: str
    base_hash: str | None
    source_capture_id: str
    source_capture_hash: str
    attachment_ids: tuple[str, ...]
    included_actions: tuple[str, ...]
    excluded_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CaptureProposalService:
    def __init__(self, *, vault_root: Path, runtime_dir: Path, actor_id: str) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.actor_id = actor_id
        self.captures = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)

    def preview(
        self, request: CaptureProposalRequest, *, now: datetime | None = None
    ) -> tuple[CaptureProposalPreview, PatchDocumentV2, bytes]:
        capture = self.captures.load(request.capture_path)
        body = request.content.strip()
        if not body:
            raise CaptureError("empty_proposal", "Capture proposal content must not be blank.")
        known = {item.attachment_id for item in capture.metadata.attachments}
        if any(item not in known for item in request.attachment_ids):
            raise CaptureError(
                "unknown_attachment", "Proposal cites an attachment not linked to the capture."
            )
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            raise CaptureError("invalid_timestamp", "Proposal timestamp must include a timezone.")
        moment = moment.astimezone(timezone.utc)
        suffix = hashlib.sha256(
            "\0".join(
                (
                    capture.metadata.capture_id,
                    capture.content_hash,
                    request.action,
                    request.target_path,
                    body,
                )
            ).encode()
        ).hexdigest()[:8]
        proposal_id = generate_proposal_id(lambda: moment, lambda: suffix)
        operation: PatchOperationV2
        if request.create_target:
            if (self.vault_root / request.target_path).exists():
                raise CaptureError("target_exists", "The proposed target already exists.")
            operation = CreateFile(
                "op-capture-create", request.target_path, "absent", body.rstrip() + "\n"
            )
            operation_name = "create_file"
            base_hash = None
        else:
            try:
                source = read_vault_markdown(self.vault_root, request.target_path)
            except VaultAccessError as exc:
                raise CaptureError(
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
            operation = PatchHumanFile(
                "op-capture-append", request.target_path, base_hash, "".join(diff[2:])
            )
            operation_name = "patch_human_file"
        patch = PatchDocumentV2(2, proposal_id, (operation,))
        timestamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        metadata = ProposalMetadata(
            id=proposal_id,
            schema_version=1,
            patch_schema_version=2,
            lifecycle_schema_version=1,
            title=f"Capture follow-up: {request.action}",
            description=f"Reviewed follow-up from {capture.metadata.title}",
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
            related_sources=(capture.path,),
            extensions={
                "source_capture_hash": capture.content_hash,
                "attachment_ids": list(request.attachment_ids),
                "included_actions": list(request.included_actions),
                "excluded_actions": list(request.excluded_actions),
            },
        )
        proposal_body = "\n".join(
            [
                "# Capture evidence",
                "",
                f"- Capture: `[[{capture.path}]]`",
                f"- Capture hash: `{capture.content_hash}`",
                f"- Attachments: {', '.join(request.attachment_ids) or 'none'}",
                "",
                "## Proposed action",
                "",
                f"- Target: `{request.target_path}`",
                f"- Operation: `{operation_name}`",
                f"- Included: {', '.join(request.included_actions) or 'none listed'}",
                f"- Excluded: {', '.join(request.excluded_actions) or 'none listed'}",
                "",
                "```markdown",
                body,
                "```",
                "",
                "No external canonical artifact changes until this proposal is reviewed, approved, and applied.",
            ]
        )
        preview = CaptureProposalPreview(
            proposal_id,
            request.target_path,
            operation_name,
            base_hash,
            capture.metadata.capture_id,
            capture.content_hash,
            request.attachment_ids,
            request.included_actions,
            request.excluded_actions,
        )
        return preview, patch, serialize_proposal_markdown(metadata, proposal_body)

    def publish(
        self, request: CaptureProposalRequest, *, now: datetime | None = None
    ) -> dict[str, object]:
        preview, patch, markdown = self.preview(request, now=now)
        target = self.vault_root / "proposals" / preview.proposal_id
        target.parent.mkdir(parents=True, exist_ok=True)
        created = False
        published = False
        fd = -1
        try:
            target.mkdir(exist_ok=False)
            created = True
            fd = os.open(
                target, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            )
            atomic_write_file_secure(fd, "proposal.md", markdown)
            atomic_write_file_secure(fd, "patches.json", serialize_patch_json_bytes(patch))
            published = True
        except FileExistsError as exc:
            raise CaptureError(
                "proposal_exists", "Equivalent capture proposal already exists."
            ) from exc
        except (OSError, AtomicWriteError) as exc:
            raise CaptureError("proposal_publish_failed", str(exc)) from exc
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
