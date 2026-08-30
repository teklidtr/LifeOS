"""MCP adapters for evidence-grounded, externally reasoned research workflows."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations

from lifeos.facade.authorization import ConsequentialAuthorizer
from lifeos.facade.errors import ToolUnavailableError
from lifeos.facade.read_only import (
    VaultContextRequest,
    WikiSearchRequest,
    get_vault_context,
    search_wiki,
)
from lifeos.facade.research_tools import (
    RESEARCH_CAPTURE_DESCRIPTOR,
    RESEARCH_CREATE_WIKI_PROPOSAL_DESCRIPTOR,
    ResearchEvidenceCaptureRequest,
    ResearchWikiProposalRequest,
    capture_research_evidence,
    create_research_wiki_proposal,
)
from lifeos.mcp.activity_store import MCPActivityStore
from lifeos.mcp.models import (
    CreateWikiProposalMCPResult,
    ResearchCaptureMCPResult,
    ResearchQueryContextMCPResult,
)
from lifeos.mcp.server import _strict_tool
from lifeos.registry import Registry
from lifeos.runtime.activity import push_activity_actor, reset_activity_actor

Invoke = Callable[[Callable[[], object]], object]
RefreshForIngestion = Callable[[str], None]

RESEARCH_QUERY_MCP_DESCRIPTION = (
    "Build a read-only research context from the existing LifeOS vault by composing the "
    "authoritative vault-context and durable-wiki search surfaces. This persists no query, "
    "answer, raw source, or proposal. The external agent decides whether the returned evidence "
    "is sufficient and whether any reported gap is material enough to research externally."
)
RESEARCH_CAPTURE_MCP_DESCRIPTION = (
    f"{RESEARCH_CAPTURE_DESCRIPTOR.description} The external agent, not LifeOS core, obtains "
    "the source and submits only the selected evidence snapshot. captured_by is intentionally "
    "absent from the tool schema and is taken from the authenticated/request or trusted local "
    "actor. Identical source snapshots are reused, acquisition reasons are linked idempotently, "
    "and changed snapshots remain distinct. The returned raw/ source must pass normal registry "
    "preflight and ingestion/proposal provenance before any durable wiki evolution."
)
RESEARCH_CREATE_WIKI_PROPOSAL_MCP_DESCRIPTION = (
    f"{RESEARCH_CREATE_WIKI_PROPOSAL_DESCRIPTOR.description} Use only when research produced a "
    "reusable durable delta not already represented in the wiki. Supply the exact source_path "
    "and acquisition_id returned by research_capture_evidence. LifeOS revalidates the immutable "
    "research snapshot and acquisition after registry preflight, binds the acquisition ID beside "
    "the raw source path/hash in proposal provenance, and creates only a normal draft proposal."
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
    runtime_dir: Path,
    registry: Registry,
    activity: MCPActivityStore,
    invoke: Invoke,
    authorizer: ConsequentialAuthorizer,
    refresh_for_ingestion: RefreshForIngestion,
) -> list[Tool]:
    """Build read-only query, narrow evidence capture, and acquisition-bound synthesis tools."""

    def research_query_context_tool(
        query: str,
        focus_paths: list[str] | None = None,
        limit: int = 8,
    ) -> ResearchQueryContextMCPResult:
        def op() -> ResearchQueryContextMCPResult:
            context = get_vault_context(
                vault_root=vault_root,
                request=VaultContextRequest(
                    question=query,
                    focus_paths=tuple(focus_paths or ()),
                    limit=limit,
                    mode="external",
                ),
                runtime_dir=runtime_dir,
            )
            wiki = search_wiki(
                vault_root=vault_root,
                request=WikiSearchRequest(query=query, limit=limit, mode="external"),
            )
            source_paths = list(
                dict.fromkeys(
                    [item.path for item in context.sources]
                    + [item.path for item in wiki.hits]
                )
            )
            activity.append(
                tool="research_query_context",
                focus_paths=list(focus_paths or ()),
                instruction_ids=[item.id for item in context.instructions],
                source_paths=source_paths,
            )
            return {
                "query": query,
                "context_sources": [
                    {
                        "path": item.path,
                        "title": item.title,
                        "description": item.description,
                        "excerpt": item.excerpt,
                        "score": item.score,
                    }
                    for item in context.sources
                ],
                "wiki_hits": [
                    {
                        "path": item.path,
                        "title": item.title,
                        "description": item.description,
                        "excerpt": item.excerpt,
                        "score": item.score,
                    }
                    for item in wiki.hits
                ],
                "evidence_gaps": list(context.evidence_gaps),
                "omissions": list(context.omissions),
                "persistence": "none",
                "decision_authority": "external-agent",
            }

        return cast(ResearchQueryContextMCPResult, invoke(op))

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

    def research_create_wiki_proposal_tool(
        source_path: str,
        acquisition_id: str,
        target_path: str,
        title: str,
        body: str,
        tags: list[str] | None = None,
        tag_rationale: str | None = None,
    ) -> CreateWikiProposalMCPResult:
        def op() -> CreateWikiProposalMCPResult:
            refresh_for_ingestion(source_path)
            result = create_research_wiki_proposal(
                vault_root=vault_root,
                registry=registry,
                request=ResearchWikiProposalRequest(
                    source_path=source_path,
                    acquisition_id=acquisition_id,
                    target_path=target_path,
                    title=title,
                    body=body,
                    tags=tuple(tags or ()),
                    tag_rationale=tag_rationale,
                ),
            )
            activity.append(
                tool="research_create_wiki_proposal",
                source_paths=[source_path],
                proposal_id=result.proposal_id,
                target_paths=[result.target_path],
                operation_count=1,
            )
            return {
                "proposal_id": result.proposal_id,
                "proposal_path": result.proposal_path,
                "target_path": result.target_path,
                "status": "draft",
            }

        return cast(CreateWikiProposalMCPResult, invoke(op))

    return [
        _strict_tool(
            research_query_context_tool,
            name="research_query_context",
            description=RESEARCH_QUERY_MCP_DESCRIPTION,
            annotations=ToolAnnotations(
                title="Build research query context",
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        ),
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
        ),
        _strict_tool(
            research_create_wiki_proposal_tool,
            name="research_create_wiki_proposal",
            description=RESEARCH_CREATE_WIKI_PROPOSAL_MCP_DESCRIPTION,
            annotations=ToolAnnotations(
                title="Create research-backed wiki proposal",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=False,
            ),
        ),
    ]
