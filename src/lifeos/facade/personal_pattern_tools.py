"""Facade for evidence-bounded external-agent personal-pattern proposals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lifeos.facade.errors import (
    ToolConflictError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
)
from lifeos.facade.models import ToolDescriptor, ToolEffect
from lifeos.markdown.parser import parse_markdown_note
from lifeos.patterns.agent_assistance import (
    AgentPatternReviewPayload,
    PatternSemanticSuggestion,
    publish_agent_pattern_proposal,
)
from lifeos.patterns.artifact import PatternArtifactService
from lifeos.patterns.contracts import (
    EvidenceRole,
    PatternConfidence,
    PatternError,
    PatternEvidence,
    PatternOrigin,
)
from lifeos.patterns.proposals import (
    CreatePatternSeedRequest,
    PatternProposalService,
    RevisePatternRequest,
)
from lifeos.registry.file_tracking import hash_file_content
from lifeos.retrieval import RetrievalError, RetrievalScope, scope_decision
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.vault import VaultAccessError, is_markdown_path, read_vault_bytes

PERSONAL_PATTERN_PROPOSE_DESCRIPTOR = ToolDescriptor(
    name="personal_pattern.propose",
    description=(
        "Create an evidence-version-bound draft proposal for a new personal-pattern seed."
    ),
    effect=ToolEffect.PROPOSAL_PRODUCING,
)
PERSONAL_PATTERN_REVIEW_DESCRIPTOR = ToolDescriptor(
    name="personal_pattern.review_proposal",
    description=(
        "Create an evidence-version-bound draft revision of an existing personal pattern."
    ),
    effect=ToolEffect.PROPOSAL_PRODUCING,
)


@dataclass(frozen=True, slots=True)
class ObservedPatternEvidence:
    path: str
    content_hash: str
    role: EvidenceRole
    observation_id: str | None = None
    event_id: str | None = None

    def __post_init__(self) -> None:
        try:
            PatternEvidence(
                path=self.path,
                content_hash=self.content_hash,
                role=self.role,
                observation_id=self.observation_id,
                event_id=self.event_id,
            )
        except PatternError as exc:
            raise ValueError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class AgentPatternSemanticInput:
    hypothesis: str
    rationale: str
    proposed_confidence: PatternConfidence
    competing_explanations: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def suggestion(self) -> PatternSemanticSuggestion:
        return PatternSemanticSuggestion(
            hypothesis=self.hypothesis,
            rationale=self.rationale,
            competing_explanations=self.competing_explanations,
            limitations=self.limitations,
            proposed_confidence=self.proposed_confidence,
        )


@dataclass(frozen=True, slots=True)
class ProposeAgentPatternRequest:
    target_path: str
    pattern_id: str
    title: str
    description: str
    semantic: AgentPatternSemanticInput
    evidence: tuple[ObservedPatternEvidence, ...]
    allow_protected: bool = False


@dataclass(frozen=True, slots=True)
class ReviewAgentPatternRequest:
    target_path: str
    observed_pattern_hash: str
    semantic: AgentPatternSemanticInput
    evidence: tuple[ObservedPatternEvidence, ...]
    allow_protected: bool = False


@dataclass(frozen=True, slots=True)
class AgentPatternProposalResult:
    state: Literal["draft", "no-change"]
    proposal_id: str | None
    proposal_path: str | None
    target_path: str

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "proposal_id": self.proposal_id,
            "proposal_path": self.proposal_path,
            "target_path": self.target_path,
        }


def _require_request_shape(
    *,
    evidence: tuple[ObservedPatternEvidence, ...],
    allow_protected: bool,
) -> None:
    if type(allow_protected) is not bool:
        raise ToolValidationError("allow_protected must be a boolean")
    if not evidence:
        raise ToolValidationError("At least one selected evidence snapshot is required")
    if len(evidence) > 32:
        raise ToolValidationError("At most 32 selected evidence snapshots are supported")


def _require_external_evidence_path(
    *,
    vault_root: Path,
    path: str,
    allow_protected: bool,
) -> None:
    if not is_markdown_path(path):
        raise ToolValidationError("Personal-pattern evidence must be canonical Markdown")
    try:
        policy = load_retrieval_policy(vault_root)
        decision = scope_decision(
            path,
            scope=RetrievalScope(paths=(path,), allow_protected=allow_protected),
            policy=policy,
            mode="external",
        )
    except RetrievalError as exc:
        raise ToolExecutionError("Retrieval policy is invalid") from exc
    if not decision.allowed:
        raise ToolValidationError(
            "Selected evidence path is unavailable under the external retrieval policy"
        )


def _verified_evidence(
    *,
    vault_root: Path,
    evidence: tuple[ObservedPatternEvidence, ...],
    allow_protected: bool,
) -> tuple[PatternEvidence, ...]:
    verified: list[PatternEvidence] = []
    for observed in evidence:
        _require_external_evidence_path(
            vault_root=vault_root,
            path=observed.path,
            allow_protected=allow_protected,
        )
        try:
            content = read_vault_bytes(vault_root, observed.path)
        except VaultAccessError as exc:
            if exc.code == "not-found":
                raise ToolNotFoundError("Selected personal-pattern evidence is missing") from exc
            if exc.code in {"invalid-path", "unsafe-symlink"}:
                raise ToolValidationError("Selected personal-pattern evidence path is unsafe") from exc
            raise ToolExecutionError("Could not read selected personal-pattern evidence") from exc
        current_hash = f"sha256:{hash_file_content(content)}"
        if current_hash != observed.content_hash:
            raise ToolConflictError(
                "Selected personal-pattern evidence changed after the agent inspected it"
            )
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ToolExecutionError("Selected personal-pattern evidence is not valid UTF-8") from exc
        parsed = parse_markdown_note(vault_root / observed.path, content=text)
        raw_source_id = parsed.frontmatter.get("id")
        source_id = raw_source_id if isinstance(raw_source_id, str) and raw_source_id.strip() else None
        verified.append(
            PatternEvidence(
                path=observed.path,
                content_hash=current_hash,
                role=observed.role,
                source_id=source_id,
                observation_id=observed.observation_id,
                event_id=observed.event_id,
            )
        )
    return tuple(verified)


def _publish(
    *,
    vault_root: Path,
    request: CreatePatternSeedRequest | RevisePatternRequest,
    semantic: AgentPatternSemanticInput,
    evidence: tuple[PatternEvidence, ...],
    expected_base_hash: str | None,
) -> AgentPatternProposalResult:
    suggestion = semantic.suggestion()
    review = AgentPatternReviewPayload(suggestion=suggestion, evidence=evidence)
    try:
        result = publish_agent_pattern_proposal(
            PatternProposalService(
                vault_root=vault_root,
                actor_id="lifeos.external-agent.personal-pattern",
            ),
            request,
            review_payload=review,
            expected_base_hash=expected_base_hash,
        )
    except PatternError as exc:
        if exc.code == "no_change":
            return AgentPatternProposalResult("no-change", None, None, request.target_path)
        if exc.code in {"stale_target", "target_exists", "duplicate_identity"}:
            raise ToolConflictError(str(exc)) from exc
        if exc.code in {"not-found"}:
            raise ToolNotFoundError(str(exc)) from exc
        if exc.code in {
            "invalid_field",
            "invalid_hash",
            "invalid_evidence_path",
            "invalid_evidence_role",
            "invalid_transition",
            "unsupported_artifact",
            "empty_revision",
        }:
            raise ToolValidationError(str(exc)) from exc
        raise ToolExecutionError("Could not create personal-pattern draft proposal") from exc
    proposal_id = result.get("proposal_id")
    proposal_path = result.get("proposal_path")
    assert isinstance(proposal_id, str)
    assert isinstance(proposal_path, str)
    return AgentPatternProposalResult("draft", proposal_id, proposal_path, request.target_path)


def propose_agent_pattern(
    *,
    vault_root: Path,
    request: ProposeAgentPatternRequest,
) -> AgentPatternProposalResult:
    _require_request_shape(evidence=request.evidence, allow_protected=request.allow_protected)
    verified = _verified_evidence(
        vault_root=vault_root,
        evidence=request.evidence,
        allow_protected=request.allow_protected,
    )
    if not any(item.role == "supporting" for item in verified):
        raise ToolValidationError("A new personal-pattern hypothesis requires supporting evidence")
    return _publish(
        vault_root=vault_root,
        request=CreatePatternSeedRequest(
            target_path=request.target_path,
            pattern_id=request.pattern_id,
            title=request.title,
            description=request.description,
            statement=request.semantic.hypothesis,
            confidence=request.semantic.proposed_confidence,
            origin=PatternOrigin("agent"),
            evidence=verified,
            transition_reason=(
                "Agent-assisted evidence-bounded seed draft; trusted review is required."
            ),
        ),
        semantic=request.semantic,
        evidence=verified,
        expected_base_hash=None,
    )


def review_agent_pattern(
    *,
    vault_root: Path,
    request: ReviewAgentPatternRequest,
) -> AgentPatternProposalResult:
    _require_request_shape(evidence=request.evidence, allow_protected=request.allow_protected)
    try:
        PatternEvidence(
            path="patterns/hash-check.md",
            content_hash=request.observed_pattern_hash,
            role="contextual",
        )
    except PatternError as exc:
        raise ToolValidationError("observed_pattern_hash must be an exact sha256 content hash") from exc
    verified = _verified_evidence(
        vault_root=vault_root,
        evidence=request.evidence,
        allow_protected=request.allow_protected,
    )
    try:
        current = PatternArtifactService(vault_root=vault_root).load(request.target_path)
    except PatternError as exc:
        if exc.code == "not-found":
            raise ToolNotFoundError(str(exc)) from exc
        raise ToolValidationError(str(exc)) from exc
    if current.content_hash != request.observed_pattern_hash:
        raise ToolConflictError("The personal pattern changed after the agent inspected it")
    if (
        current.metadata.statement == request.semantic.hypothesis
        and current.metadata.confidence == request.semantic.proposed_confidence
        and current.metadata.evidence == verified
    ):
        return AgentPatternProposalResult("no-change", None, None, request.target_path)
    return _publish(
        vault_root=vault_root,
        request=RevisePatternRequest(
            target_path=request.target_path,
            transition_reason=(
                "Agent-assisted evidence-bounded pattern review; trusted review is required."
            ),
            statement=request.semantic.hypothesis,
            evidence=verified,
            confidence=request.semantic.proposed_confidence,
        ),
        semantic=request.semantic,
        evidence=verified,
        expected_base_hash=request.observed_pattern_hash,
    )
