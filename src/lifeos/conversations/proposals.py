"""Turn knowledge-conversation outcomes into reviewable LifeOS proposals."""

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
from lifeos.vault import VaultAccessError, read_vault_markdown

from .artifact import ConversationArtifactService
from .contracts import ConversationError

ConversationProposalAction = Literal[
    "create_capture",
    "draft_note",
    "append_section",
    "suggest_links",
    "research_questions",
    "extract_claims",
    "flashcard_candidates",
    "mark_contradiction",
    "mark_unresolved_question",
]

_ACTION_HEADINGS: dict[str, str] = {
    "create_capture": "Conversation capture",
    "draft_note": "Draft from conversation",
    "append_section": "Conversation-derived section",
    "suggest_links": "Suggested links",
    "research_questions": "Questions for later research",
    "extract_claims": "Extracted claims and insights",
    "flashcard_candidates": "Flashcard candidates",
    "mark_contradiction": "Contradictions",
    "mark_unresolved_question": "Unresolved questions",
}


@dataclass(frozen=True, slots=True)
class ConversationProposalRequest:
    conversation_path: str
    turn_id: str
    action: ConversationProposalAction
    target_path: str
    content: str
    title: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationProposalPreview:
    proposal_id: str
    action: str
    target_path: str
    operation: str
    base_hash: str | None
    unified_diff: str | None
    new_content: str | None
    evidence: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "action": self.action,
            "target_path": self.target_path,
            "operation": self.operation,
            "base_hash": self.base_hash,
            "unified_diff": self.unified_diff,
            "new_content": self.new_content,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class ConversationProposalResult:
    proposal_id: str
    proposal_path: str
    preview: ConversationProposalPreview

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_path": self.proposal_path,
            "preview": self.preview.to_dict(),
        }


def _utc(value: datetime | None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ConversationError("invalid_timestamp", "Proposal timestamp must be timezone-aware.")
    return moment.astimezone(timezone.utc)


def _proposal_id(moment: datetime, request: ConversationProposalRequest) -> str:
    fingerprint = "\0".join(
        (request.conversation_path, request.turn_id, request.action, request.target_path, request.content)
    )
    suffix = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:8]
    return generate_proposal_id(lambda: moment, lambda: suffix)


def _candidate_content(request: ConversationProposalRequest) -> str:
    heading = _ACTION_HEADINGS[request.action]
    body = request.content.strip()
    if not body:
        raise ConversationError("empty_proposal", "Conversation proposal content must not be blank.")
    title = request.title.strip() if request.title else heading
    if request.action in {"create_capture", "draft_note"}:
        note_type = "capture" if request.action == "create_capture" else "note"
        return f"---\ntype: {note_type}\ntitle: {title}\n---\n\n# {title}\n\n{body}\n"
    return f"\n\n## {heading}\n\n{body}\n"


class ConversationProposalService:
    def __init__(self, *, vault_root: Path, runtime_dir: Path, actor_id: str = "local-user") -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.actor_id = actor_id
        self.artifacts = ConversationArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)

    def preview(
        self,
        request: ConversationProposalRequest,
        *,
        now: datetime | None = None,
    ) -> tuple[ConversationProposalPreview, PatchDocumentV2, ProposalMetadata, bytes]:
        artifact = self.artifacts.load(request.conversation_path)
        turn = next((item for item in artifact.turns if item.turn_id == request.turn_id), None)
        if turn is None:
            raise ConversationError("turn_not_found", "Proposal source turn was not found.")
        if not turn.evidence:
            raise ConversationError("missing_evidence", "Conversation proposals require cited source evidence.")
        if request.action not in _ACTION_HEADINGS:
            raise ConversationError("invalid_action", "Conversation proposal action is unsupported.")
        moment = _utc(now)
        proposal_id = _proposal_id(moment, request)
        candidate = _candidate_content(request)
        create = request.action in {"create_capture", "draft_note"}
        base_hash: str | None = None
        unified_diff: str | None = None
        operation: CreateFile | PatchHumanFile
        if create:
            if (self.vault_root / request.target_path).exists():
                raise ConversationError("target_exists", "The proposed target already exists.")
            operation = CreateFile("op-conversation-create", request.target_path, "absent", candidate)
            operation_name = "create_file"
            new_content: str | None = candidate
        else:
            try:
                source = read_vault_markdown(self.vault_root, request.target_path)
            except VaultAccessError as exc:
                raise ConversationError(exc.code, str(exc), {"target_path": request.target_path}) from exc
            updated = source.content.rstrip() + candidate
            base_hash = f"sha256:{content_hash(source.content)}"
            lines = tuple(
                difflib.unified_diff(
                    source.content.splitlines(keepends=True),
                    updated.splitlines(keepends=True),
                    fromfile=request.target_path,
                    tofile=request.target_path,
                )
            )
            unified_diff = "".join(lines[2:])
            operation = PatchHumanFile(
                "op-conversation-append", request.target_path, base_hash, unified_diff
            )
            operation_name = "patch_human_file"
            new_content = None
        patch_document = PatchDocumentV2(2, proposal_id, (operation,))
        evidence: tuple[dict[str, object], ...] = tuple(
            {
                "evidence_id": item.evidence_id,
                "path": item.path,
                "heading": item.heading,
                "source_hash": item.source_hash,
                "chunk_hash": item.chunk_hash,
            }
            for item in turn.evidence
        )
        timestamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        metadata = ProposalMetadata(
            id=proposal_id,
            schema_version=1,
            patch_schema_version=2,
            lifecycle_schema_version=1,
            title=f"Conversation proposal: {_ACTION_HEADINGS[request.action]}",
            description=f"User-reviewed {request.action.replace('_', ' ')} from {artifact.metadata.title}",
            status=ProposalStatus.DRAFT,
            risk=ProposalRisk.MEDIUM if not create else ProposalRisk.LOW,
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
            related_sources=tuple(dict.fromkeys((request.conversation_path, *(item.path for item in turn.evidence)))),
            extensions={
                "knowledge_conversation": {
                    "conversation_id": artifact.metadata.conversation_id,
                    "turn_id": turn.turn_id,
                    "action": request.action,
                    "target_path": request.target_path,
                    "evidence": list(evidence),
                }
            },
        )
        body_lines = [
            "## Proposed outcome",
            "",
            f"- Action: `{request.action}`",
            f"- Target: `{request.target_path}`",
            f"- Operation: `{operation_name}`",
            f"- Base hash: `{base_hash or 'absent'}`",
            "",
            "## Source evidence",
            "",
        ]
        body_lines.extend(
            f"- `{item['evidence_id']}` · `{item['path']}`"
            + (f" · `{item['heading']}`" if item["heading"] else "")
            for item in evidence
        )
        body_lines.extend(["", "## Candidate content", "", "```markdown", request.content.strip(), "```", ""])
        proposal_markdown = serialize_proposal_markdown(metadata, "\n".join(body_lines))
        preview = ConversationProposalPreview(
            proposal_id,
            request.action,
            request.target_path,
            operation_name,
            base_hash,
            unified_diff,
            new_content,
            evidence,
        )
        return preview, patch_document, metadata, proposal_markdown

    def publish(
        self, request: ConversationProposalRequest, *, now: datetime | None = None
    ) -> ConversationProposalResult:
        preview, patch_document, _metadata, proposal_markdown = self.preview(request, now=now)
        proposals_root = self.vault_root / "proposals"
        proposal_dir = proposals_root / preview.proposal_id
        proposals_root.mkdir(parents=True, exist_ok=True)
        created = False
        published = False
        directory_fd = -1
        try:
            proposal_dir.mkdir(exist_ok=False)
            created = True
            directory_fd = os.open(
                proposal_dir,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            atomic_write_file_secure(directory_fd, "proposal.md", proposal_markdown)
            atomic_write_file_secure(
                directory_fd, "patches.json", serialize_patch_json_bytes(patch_document)
            )
            published = True
        except FileExistsError as exc:
            raise ConversationError("proposal_exists", "Conversation proposal already exists.") from exc
        except (OSError, AtomicWriteError) as exc:
            raise ConversationError("proposal_publish_failed", str(exc)) from exc
        finally:
            if directory_fd >= 0:
                os.close(directory_fd)
            if created and not published:
                shutil.rmtree(proposal_dir, ignore_errors=True)
        return ConversationProposalResult(
            preview.proposal_id, f"proposals/{preview.proposal_id}", preview
        )
