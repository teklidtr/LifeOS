"""MCP adapters for evidence-bounded personal-pattern draft proposals."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, cast

from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

from lifeos.facade.personal_pattern_tools import (
    PERSONAL_PATTERN_PROPOSE_DESCRIPTOR,
    PERSONAL_PATTERN_REVIEW_DESCRIPTOR,
    AgentPatternSemanticInput,
    ObservedPatternEvidence,
    ProposeAgentPatternRequest,
    ReviewAgentPatternRequest,
    propose_agent_pattern,
    review_agent_pattern,
)
from lifeos.mcp.activity_store import MCPActivityStore
from lifeos.mcp.exploration_tools import _strict_tool

Invoke = Callable[[Callable[[], object]], object]

PERSONAL_PATTERN_PROPOSE_MCP_DESCRIPTION = (
    f"{PERSONAL_PATTERN_PROPOSE_DESCRIPTOR.description} Supply only evidence the agent actually "
    "inspected, with each exact path and content_hash snapshot plus its supporting, contesting, "
    "or contextual role. LifeOS independently re-reads and verifies every source under the "
    "external retrieval policy before publishing. The hypothesis, rationale, counter-evidence, "
    "competing explanations, limitations, and confidence remain proposal review context. This "
    "creates only a seed draft and never establishes a user trait or writes patterns/ directly."
)
PERSONAL_PATTERN_REVIEW_MCP_DESCRIPTION = (
    f"{PERSONAL_PATTERN_REVIEW_DESCRIPTOR.description} Bind the review to the exact canonical "
    "pattern hash the agent inspected and to exact selected evidence snapshots. LifeOS rejects "
    "changed, missing, or policy-denied sources and returns no-change without creating a draft "
    "when the proposed canonical statement/evidence/confidence are unchanged. This tool cannot "
    "approve, apply, diagnose, or promote a hypothesis to active."
)


class PersonalPatternEvidenceMCPInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str
    content_hash: str
    role: Literal["supporting", "contesting", "contextual"]
    observation_id: str | None = None
    event_id: str | None = None


class PersonalPatternSemanticMCPInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    hypothesis: str
    rationale: str
    proposed_confidence: Literal["low", "medium", "high"]
    competing_explanations: list[str] | None = None
    limitations: list[str] | None = None


def _semantic(value: PersonalPatternSemanticMCPInput) -> AgentPatternSemanticInput:
    return AgentPatternSemanticInput(
        hypothesis=value.hypothesis,
        rationale=value.rationale,
        proposed_confidence=value.proposed_confidence,
        competing_explanations=tuple(value.competing_explanations or ()),
        limitations=tuple(value.limitations or ()),
    )


def _evidence(values: list[PersonalPatternEvidenceMCPInput]) -> tuple[ObservedPatternEvidence, ...]:
    return tuple(
        ObservedPatternEvidence(
            path=item.path,
            content_hash=item.content_hash,
            role=item.role,
            observation_id=item.observation_id,
            event_id=item.event_id,
        )
        for item in values
    )


def build_personal_pattern_tools(
    *,
    vault_root: Path,
    activity: MCPActivityStore,
    invoke: Invoke,
) -> tuple[Tool, ...]:
    """Build draft-only personal-pattern tools for the shared MCP runtime."""

    def personal_pattern_propose_tool(
        target_path: str,
        pattern_id: str,
        title: str,
        description: str,
        semantic: PersonalPatternSemanticMCPInput,
        evidence: list[PersonalPatternEvidenceMCPInput],
        allow_protected: bool = False,
    ) -> dict[str, object]:
        def op() -> dict[str, object]:
            result = propose_agent_pattern(
                vault_root=vault_root,
                request=ProposeAgentPatternRequest(
                    target_path=target_path,
                    pattern_id=pattern_id,
                    title=title,
                    description=description,
                    semantic=_semantic(semantic),
                    evidence=_evidence(evidence),
                    allow_protected=allow_protected,
                ),
            )
            activity.append(
                tool="personal_pattern_propose",
                source_paths=[item.path for item in evidence],
                proposal_id=result.proposal_id,
                target_paths=[target_path],
                operation_count=1 if result.state == "draft" else 0,
            )
            return result.to_dict()

        return cast(dict[str, object], invoke(op))

    def personal_pattern_review_proposal_tool(
        target_path: str,
        observed_pattern_hash: str,
        semantic: PersonalPatternSemanticMCPInput,
        evidence: list[PersonalPatternEvidenceMCPInput],
        allow_protected: bool = False,
    ) -> dict[str, object]:
        def op() -> dict[str, object]:
            result = review_agent_pattern(
                vault_root=vault_root,
                request=ReviewAgentPatternRequest(
                    target_path=target_path,
                    observed_pattern_hash=observed_pattern_hash,
                    semantic=_semantic(semantic),
                    evidence=_evidence(evidence),
                    allow_protected=allow_protected,
                ),
            )
            activity.append(
                tool="personal_pattern_review_proposal",
                source_paths=[item.path for item in evidence],
                proposal_id=result.proposal_id,
                target_paths=[target_path],
                operation_count=1 if result.state == "draft" else 0,
            )
            return result.to_dict()

        return cast(dict[str, object], invoke(op))

    annotations = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
    return (
        _strict_tool(
            personal_pattern_propose_tool,
            name="personal_pattern_propose",
            description=PERSONAL_PATTERN_PROPOSE_MCP_DESCRIPTION,
            title="Propose personal pattern",
        ).model_copy(update={"annotations": annotations}),
        _strict_tool(
            personal_pattern_review_proposal_tool,
            name="personal_pattern_review_proposal",
            description=PERSONAL_PATTERN_REVIEW_MCP_DESCRIPTION,
            title="Review personal pattern",
        ).model_copy(update={"annotations": annotations}),
    )
