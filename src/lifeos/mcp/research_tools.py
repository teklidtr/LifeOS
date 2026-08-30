"""MCP adapter for controlled, hash-bound external research evidence capture."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations

from lifeos.facade.authorization import ConsequentialAuthorizer
from lifeos.facade.errors import ToolUnavailableError
from lifeos.facade.research_tools import (
    RESEARCH_CAPTURE_DESCRIPTOR,
    ResearchEvidenceCaptureRequest,
    capture_research_evidence,
)
from lifeos.mcp.activity_store import MCPActivityStore
from lifeos.mcp.models import ResearchCaptureMCPResult
from lifeos.mcp.server import _strict_tool
from lifeos.runtime.activity import push_activity_actor, reset_activity_actor

Invoke = Callable[[Callable[[], object]], object]

RESEARCH_CAPTURE_MCP_DESCRIPTION = (
    f"{RESEARCH_CAPTURE_DESCRIPTOR.description} The external agent, not LifeOS core, obtains "
    "the source and submits only the selected evidence snapshot. captured_by is intentionally "
    "absent from the tool schema and is taken from the authenticated/request or trusted local "
    "actor. Identical source snapshots are reused, acquisition reasons are linked idempotently, "
    "and changed snapshots remain distinct. The returned raw/ source must pass normal registry "
    "preflight and ingestion/proposal provenance before any durable wiki evolution."
)


def _trusted_actor_id(
    *,
    activity: MCPActivityStore,
    authorizer: ConsequentialAuthorizer,
) -> str:
    request_actor = activity.current_actor_id()
    if request_actor is not None:
        return request_actor
    local_actor = getattr(authorizer, "actor_id", None)
    if isinstance(local_actor, str) and local_actor.strip() == local_actor and local_actor:
        return local_actor
    raise ToolUnavailableError("Trusted MCP actor identity is unavailable for research capture")


def build_research_tools(
    *,
    vault_root: Path,
    activity: MCPActivityStore,
    invoke: Invoke,
    authorizer: ConsequentialAuthorizer,
) -> list[Tool]:
    """Build the narrow canonical research-capture surface."""

    def research_capture_evidence_tool(
        evidence_text: str,
        source_title: str,
        research_reason: str,
        source_locator: str | None = None,
        source_author: str | None = None,
        source_publisher: str | None = None,
        origin_kind: str = "query",
        origin_ref: str | None = None,
        research_context: str = "",
    ) -> ResearchCaptureMCPResult:
        def op() -> ResearchCaptureMCPResult:
            actor_id = _trusted_actor_id(activity=activity, authorizer=authorizer)
            actor_token = None
            if activity.current_actor_id() is None:
                actor_token = push_activity_actor(actor_id)
            try:
                result = capture_research_evidence(
                    vault_root=vault_root,
                    trusted_actor_id=actor_id,
                    request=ResearchEvidenceCaptureRequest(
                        evidence_text=evidence_text,
                        source_title=source_title,
                        research_reason=research_reason,
                        source_locator=source_locator,
                        source_author=source_author,
                        source_publisher=source_publisher,
                        origin_kind=origin_kind,  # type: ignore[arg-type]
                        origin_ref=origin_ref,
                        research_context=research_context,
                    ),
                )
                changed_paths = (
                    [result.source_path]
                    if result.created or result.acquisition_added
                    else []
                )
                activity.append(
                    tool="research_capture_evidence",
                    source_paths=[result.source_path],
                    changed_paths=changed_paths,
                    operation_count=1 if changed_paths else 0,
                )
                return {
                    "artifact_id": result.artifact_id,
                    "source_path": result.source_path,
                    "snapshot_hash": result.snapshot_hash,
                    "acquisition_id": result.acquisition_id,
                    "created": result.created,
                    "acquisition_added": result.acquisition_added,
                }
            finally:
                if actor_token is not None:
                    reset_activity_actor(actor_token)

        return cast(ResearchCaptureMCPResult, invoke(op))

    return [
        _strict_tool(
            research_capture_evidence_tool,
            name="research_capture_evidence",
            description=RESEARCH_CAPTURE_MCP_DESCRIPTION,
            annotations=ToolAnnotations(
                title="Capture external research evidence",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
    ]
