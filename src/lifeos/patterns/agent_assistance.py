"""Provider-neutral semantic assistance and review payloads for personal-pattern drafts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol, Sequence

from lifeos.markdown.parser import parse_markdown_note
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.patches import PatchDocumentV2, serialize_patch_json_bytes
from lifeos.proposals.review_snapshot import build_review_snapshot_bytes_from_patches
from lifeos.proposals.schema import validate_metadata
from lifeos.retrieval.contracts import CancellationToken, ProviderCapabilities, ProviderError
from lifeos.vault import VaultAccessError, read_vault_bytes

from .contracts import PatternConfidence, PatternError, PatternEvidence
from .proposals import PatternProposalRequest, PatternProposalService, _publish_proposal

PatternAssistanceState = Literal[
    "ready",
    "no-model",
    "no-proposal",
    "timeout",
    "provider-unavailable",
    "malformed-output",
]

_MAX_SEMANTIC_TEXT = 2_000
_MAX_SEMANTIC_ITEMS = 12


def _bounded_text(value: str, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-blank string")
    normalized = " ".join(value.split())
    if len(normalized) > _MAX_SEMANTIC_TEXT:
        raise ValueError(f"{field} exceeds {_MAX_SEMANTIC_TEXT} characters")
    return normalized


def _bounded_items(values: Sequence[str], field: str) -> tuple[str, ...]:
    items = tuple(_bounded_text(value, field) for value in values)
    if len(items) > _MAX_SEMANTIC_ITEMS:
        raise ValueError(f"{field} exceeds {_MAX_SEMANTIC_ITEMS} items")
    return items


@dataclass(frozen=True, slots=True)
class PatternSemanticSuggestion:
    """Concise provider-neutral interpretation. It is never canonical authority by itself."""

    hypothesis: str
    rationale: str
    competing_explanations: tuple[str, ...]
    limitations: tuple[str, ...]
    proposed_confidence: PatternConfidence

    def __post_init__(self) -> None:
        object.__setattr__(self, "hypothesis", _bounded_text(self.hypothesis, "hypothesis"))
        object.__setattr__(self, "rationale", _bounded_text(self.rationale, "rationale"))
        object.__setattr__(
            self,
            "competing_explanations",
            _bounded_items(self.competing_explanations, "competing_explanations"),
        )
        object.__setattr__(self, "limitations", _bounded_items(self.limitations, "limitations"))
        if self.proposed_confidence not in {"low", "medium", "high"}:
            raise ValueError("proposed_confidence must be low, medium, or high")

    def to_dict(self) -> dict[str, object]:
        return {
            "hypothesis": self.hypothesis,
            "rationale": self.rationale,
            "competing_explanations": list(self.competing_explanations),
            "limitations": list(self.limitations),
            "proposed_confidence": self.proposed_confidence,
        }


@dataclass(frozen=True, slots=True)
class PatternAssistanceRequest:
    purpose: Literal["new-pattern", "review-existing"]
    evidence: tuple[PatternEvidence, ...]
    existing_statement: str | None = None

    def __post_init__(self) -> None:
        if self.purpose not in {"new-pattern", "review-existing"}:
            raise ValueError("purpose is unsupported")
        if not self.evidence:
            raise ValueError("semantic pattern assistance requires selected evidence")
        if len(self.evidence) > 32:
            raise ValueError("semantic pattern assistance supports at most 32 evidence references")
        if self.existing_statement is not None:
            object.__setattr__(
                self,
                "existing_statement",
                _bounded_text(self.existing_statement, "existing_statement"),
            )


class PatternAssistanceProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def suggest(
        self,
        request: PatternAssistanceRequest,
        *,
        timeout_seconds: float | None,
        cancellation: CancellationToken,
    ) -> PatternSemanticSuggestion | None: ...


@dataclass(frozen=True, slots=True)
class PatternAssistanceResult:
    state: PatternAssistanceState
    suggestion: PatternSemanticSuggestion | None
    provider_disclosure: dict[str, object]
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "suggestion": None if self.suggestion is None else self.suggestion.to_dict(),
            "provider_disclosure": dict(self.provider_disclosure),
            "diagnostics": list(self.diagnostics),
        }


def assist_pattern(
    request: PatternAssistanceRequest,
    *,
    provider: PatternAssistanceProvider | None,
    timeout_seconds: float | None = 30,
    cancellation: CancellationToken | None = None,
) -> PatternAssistanceResult:
    """Run optional model assistance without granting it proposal or lifecycle authority."""
    if provider is None:
        return PatternAssistanceResult("no-model", None, {"configured": False, "sent_paths": []})
    if provider.capabilities.kind != "generation":
        return PatternAssistanceResult(
            "provider-unavailable",
            None,
            {"configured": True, "sent_paths": []},
            ("Pattern assistance requires a generation provider.",),
        )
    token = cancellation or CancellationToken()
    disclosure = {
        "configured": True,
        "adapter_key": provider.capabilities.adapter_key,
        "model_key": provider.capabilities.model_key,
        "local_only": provider.capabilities.local_only,
        "sent_paths": [item.path for item in request.evidence],
    }
    try:
        suggestion = provider.suggest(
            request,
            timeout_seconds=timeout_seconds,
            cancellation=token,
        )
    except ProviderError as exc:
        state: PatternAssistanceState = (
            "timeout" if exc.code == "timeout" else "provider-unavailable"
        )
        return PatternAssistanceResult(state, None, disclosure, (str(exc),))
    except (TypeError, ValueError) as exc:
        return PatternAssistanceResult("malformed-output", None, disclosure, (str(exc),))
    if suggestion is None:
        return PatternAssistanceResult("no-proposal", None, disclosure)
    if not isinstance(suggestion, PatternSemanticSuggestion):
        return PatternAssistanceResult(
            "malformed-output",
            None,
            disclosure,
            ("Provider returned an unsupported personal-pattern suggestion type.",),
        )
    return PatternAssistanceResult("ready", suggestion, disclosure)


@dataclass(frozen=True, slots=True)
class AgentPatternReviewPayload:
    """Digest-bound semantic review context stored only with the proposal."""

    suggestion: PatternSemanticSuggestion
    evidence: tuple[PatternEvidence, ...]

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("agent-assisted pattern proposals require selected evidence")
        if len(self.evidence) > 32:
            raise ValueError("agent-assisted pattern proposals support at most 32 evidence references")

    def to_dict(self) -> dict[str, object]:
        supporting = [item.to_dict() for item in self.evidence if item.role == "supporting"]
        contesting = [item.to_dict() for item in self.evidence if item.role == "contesting"]
        contextual = [item.to_dict() for item in self.evidence if item.role == "contextual"]
        return {
            **self.suggestion.to_dict(),
            "supporting_evidence": supporting,
            "contesting_evidence": contesting,
            "contextual_evidence": contextual,
            "authority": "proposal-only",
            "hidden_reasoning_stored": False,
        }


def _semantic_body(payload: AgentPatternReviewPayload) -> str:
    data = payload.to_dict()

    def evidence_lines(key: str) -> list[str]:
        refs = data[key]
        assert isinstance(refs, list)
        return [
            f"- `{item['path']}` at `{item['content_hash']}`"
            for item in refs
            if isinstance(item, dict)
        ] or ["- None selected."]

    competing = [f"- {item}" for item in payload.suggestion.competing_explanations] or ["- None recorded."]
    limitations = [f"- {item}" for item in payload.suggestion.limitations] or ["- None recorded."]
    return "\n".join(
        [
            "",
            "## Agent-assisted semantic review context",
            "",
            "This section is review context only. It does not establish a user trait, diagnosis, or truth.",
            "",
            f"- Proposed confidence: `{payload.suggestion.proposed_confidence}`",
            f"- Rationale: {payload.suggestion.rationale}",
            "",
            "### Supporting evidence",
            "",
            *evidence_lines("supporting_evidence"),
            "",
            "### Contesting evidence",
            "",
            *evidence_lines("contesting_evidence"),
            "",
            "### Competing explanations",
            "",
            *competing,
            "",
            "### Limitations",
            "",
            *limitations,
            "",
            "No hidden chain-of-thought is stored in this proposal.",
        ]
    )


def _reverify_review_evidence(
    vault_root: Path,
    evidence: tuple[PatternEvidence, ...],
) -> None:
    """Recheck exact evidence bytes at the final proposal-publication boundary."""
    for item in evidence:
        try:
            content = read_vault_bytes(vault_root, item.path)
        except VaultAccessError as exc:
            code = "evidence_missing" if exc.code == "not-found" else "evidence_unavailable"
            raise PatternError(
                code,
                "Selected personal-pattern evidence became unavailable before draft publication.",
                {"path": item.path},
            ) from exc
        current_hash = "sha256:" + hashlib.sha256(content).hexdigest()
        if current_hash != item.content_hash:
            raise PatternError(
                "stale_evidence",
                "Selected personal-pattern evidence changed before draft publication.",
                {
                    "path": item.path,
                    "expected_hash": item.content_hash,
                    "current_hash": current_hash,
                },
            )


def publish_agent_pattern_proposal(
    service: PatternProposalService,
    request: PatternProposalRequest,
    *,
    review_payload: AgentPatternReviewPayload,
    now: datetime | None = None,
    expected_base_hash: str | None = None,
) -> dict[str, object]:
    """Publish a normal pattern draft with additional digest-bound semantic review context."""
    preview, patch, proposal_markdown = service.preview(
        request,
        now=now,
        expected_base_hash=expected_base_hash,
    )
    parsed = parse_markdown_note(
        Path("proposal.md"),
        content=proposal_markdown.decode("utf-8"),
    )
    metadata = validate_metadata(dict(parsed.frontmatter))
    semantic = review_payload.to_dict()
    context_bytes = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    suffix = hashlib.sha256(
        preview.proposal_id.encode("utf-8") + b"\0" + context_bytes
    ).hexdigest()[:8]
    proposal_id = preview.proposal_id.rsplit("-", 1)[0] + "-" + suffix
    patch = PatchDocumentV2(patch.schema_version, proposal_id, patch.operations)
    extensions = dict(metadata.extensions)
    personal_pattern = dict(extensions.get("personal_pattern", {}))
    personal_pattern["agent_assistance"] = semantic
    extensions["personal_pattern"] = personal_pattern
    metadata = replace(metadata, id=proposal_id, extensions=extensions)
    body = parsed.body.rstrip() + "\n" + _semantic_body(review_payload) + "\n"
    proposal_bytes = serialize_proposal_markdown(metadata, body)
    patches_json = serialize_patch_json_bytes(patch)
    review_json = build_review_snapshot_bytes_from_patches(
        vault_root=service.vault_root,
        patches_json=patches_json,
    )
    _reverify_review_evidence(service.vault_root, review_payload.evidence)
    _publish_proposal(
        vault_root=service.vault_root,
        proposal_id=proposal_id,
        proposal_markdown=proposal_bytes,
        patches_json=patches_json,
        review_json=review_json,
    )
    return {
        "proposal_id": proposal_id,
        "proposal_path": f"proposals/{proposal_id}",
        "preview": {**preview.to_dict(), "proposal_id": proposal_id},
        "status": "draft",
    }
