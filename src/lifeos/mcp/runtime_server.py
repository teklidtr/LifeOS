"""User-facing MCP runtime composed from core and exploration tool surfaces."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from lifeos.coherence import CoherenceError
from lifeos.coherence_scoped import runtime_exclusion_prefix
from lifeos.facade.authorization import ConsequentialAuthorizer
from lifeos.facade.errors import ToolExecutionError
from lifeos.facade.read_only import (
    WikiSearchRequest,
    WikiSearchResult,
    push_vault_context_providers,
    reset_vault_context_providers,
    search_wiki,
)
from lifeos.facade.registry_tools import refresh_registry
from lifeos.mcp.activity_store import MCPActivityStore
from lifeos.mcp.coherence_tools import build_coherence_tools
from lifeos.mcp.exploration_tools import (
    _strict_tool,
    build_exploration_tools,
    build_policy_read_tools,
)
from lifeos.mcp.multi_source_tools import build_multi_source_ingestion_tools
from lifeos.mcp.personal_pattern_tools import build_personal_pattern_tools
from lifeos.mcp.research_tools import build_research_tools
from lifeos.mcp.server import (
    LIFEOS_MCP_INSTRUCTIONS as CORE_MCP_INSTRUCTIONS,
    WIKI_SEARCH_MCP_DESCRIPTION,
    _invoke_mcp_tool,
    create_mcp_server as create_core_mcp_server,
)
from lifeos.mcp.tool_contracts import serialize_authoritative_output
from lifeos.registry import Registry
from lifeos.retrieval import RetrievalError, RetrievalScope, scope_decision
from lifeos.retrieval.contracts import (
    push_node_local_excluded_prefixes,
    push_node_local_exclusion_predicates,
    reset_node_local_excluded_prefixes,
    reset_node_local_exclusion_predicates,
)
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.runtime.activity import (
    push_activity_runtime_dir_fd,
    reset_activity_runtime_dir_fd,
)
from lifeos.runtime_scope import build_runtime_exclusion_matcher

if TYPE_CHECKING:
    from lifeos.retrieval.contracts import EmbeddingProvider, RerankingProvider

_POLICY_READ_OVERRIDES = frozenset(
    {"vault_read_markdown", "wiki_search", "vault_context", "runtime_activity"}
)

LIFEOS_MCP_INSTRUCTIONS = (
    "Exploration is encouraged: use vault_list, vault_search, vault_read_markdown, "
    "vault_read_many, vault_links, wiki_search, vault_context, and vault_note_identity "
    "iteratively to decide what matters and what to inspect next. A canonical note's stable "
    "frontmatter id, current path, and content hash are separate facts; use vault_note_identity "
    "when rename/move continuity matters. Protected retrieval scopes remain default-deny and can "
    "cross the MCP boundary only when the user explicitly asks to include them and retrieval "
    "policy permits external disclosure. Configured node-local runtime state is excluded before "
    "all exploration and context traversal, even when it lives inside the vault. Runtime activity "
    "re-filters path metadata through the current external policy and node-local exclusion and "
    "never acts as a protected-scope bypass. Semantic interpretation belongs to the external "
    "agent. LifeOS constrains mutation, not exploration: canonical changes remain available only "
    "through bounded proposal and consequential authorization tools; there is no generic vault "
    "write, delete, move, or shell surface. For personal hypotheses, carry the exact selected "
    "path/content_hash evidence snapshots into personal_pattern_propose or "
    "personal_pattern_review_proposal; those tools independently verify source versions and "
    "store concise rationale, counter-evidence, competing explanations, and limitations only as "
    "draft review context. They never establish a user trait, promote a pattern to active, or "
    "write patterns/ directly. Folder or multi-source ingestion is one logical batch: "
    "discover the candidate sources, use vault_read_many to read the selected evidence together, "
    "carry the exact path/content_hash snapshots from vault_read_many into the batch proposal "
    "call, inspect applicable context and wiki knowledge, jointly reason about the durable delta, "
    "group that delta by target, then use ingestion_evolve_wiki_batch_proposal to create one "
    "target-reconciled draft. If any selected source changed since that read, reread it and "
    "re-reason rather than rebinding the old synthesis to new bytes. Do not loop the single-source "
    "proposal tool once per file. Zero durable changes remains a valid outcome. External research "
    "also remains agent-led: start with research_query_context when a single read-only research "
    "context is useful, or compose the lower-level context/search tools directly. When a material "
    "evidence gap requires an external source, use research_capture_evidence to preserve the "
    "selected source snapshot in raw/ with hash-bound acquisition lineage. If that research "
    "creates a reusable durable delta, use research_create_wiki_proposal with the exact returned "
    "source_path and acquisition_id; generic ingestion cannot silently choose among research "
    "acquisitions. Never send an uncaptured external claim directly to wiki mutation, and create "
    "no proposal when the answer is already represented or produces no durable delta. "
    + CORE_MCP_INSTRUCTIONS
)


def create_mcp_server(
    *,
    vault_root: Path,
    registry: Registry,
    authorizer: ConsequentialAuthorizer,
    runtime_dir: Path | None = None,
    runtime_dir_fd: int | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    reranker: RerankingProvider | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    transport_security: TransportSecuritySettings | None = None,
    stateless_http: bool = False,
    json_response: bool = False,
    excluded_core_tools: frozenset[str] = frozenset(),
) -> FastMCP:
    """Compose one MCP tool surface for local STDIO or authenticated network transport."""
    resolved_runtime_dir = runtime_dir or (vault_root / ".lifeos")

    def runtime_scoped_invoke(operation: Callable[[], object]) -> object:
        def scoped_operation() -> object:
            try:
                runtime_prefix = runtime_exclusion_prefix(
                    vault_root,
                    runtime_dir=resolved_runtime_dir,
                )
                matcher = build_runtime_exclusion_matcher(
                    vault_root,
                    runtime_dir=resolved_runtime_dir,
                    snapshot_prefix=runtime_prefix,
                )
            except CoherenceError as error:
                raise ToolExecutionError(
                    "Could not resolve configured runtime directory"
                ) from error

            def runtime_excluded(path: str) -> bool:
                try:
                    return matcher(path)
                except CoherenceError as error:
                    raise ToolExecutionError(
                        "Could not verify configured runtime exclusion"
                    ) from error

            runtime_exclusions = (runtime_prefix,) if runtime_prefix is not None else ()
            prefix_token = push_node_local_excluded_prefixes(runtime_exclusions)
            predicate_token = push_node_local_exclusion_predicates((runtime_excluded,))
            provider_tokens = push_vault_context_providers(
                embedding_provider=embedding_provider,
                reranker=reranker,
            )
            try:
                return operation()
            finally:
                reset_vault_context_providers(provider_tokens)
                reset_node_local_exclusion_predicates(predicate_token)
                reset_node_local_excluded_prefixes(prefix_token)

        return _invoke_mcp_tool(scoped_operation)

    activity_runtime_token = push_activity_runtime_dir_fd(runtime_dir_fd)
    try:
        core = create_core_mcp_server(
            vault_root=vault_root,
            registry=registry,
            authorizer=authorizer,
            runtime_dir=resolved_runtime_dir,
        )
        activity = MCPActivityStore(resolved_runtime_dir, runtime_dir_fd=runtime_dir_fd)
    finally:
        reset_activity_runtime_dir_fd(activity_runtime_token)

    def refresh_research_for_ingestion(source_path: str) -> None:
        try:
            policy = load_retrieval_policy(vault_root)
        except RetrievalError as error:
            raise ToolExecutionError("Retrieval policy is invalid") from error
        scope = RetrievalScope()

        def allowed(path: str) -> bool:
            if path.startswith("conversations/") or path.startswith("proposals/"):
                return False
            try:
                return scope_decision(
                    path,
                    scope=scope,
                    policy=policy,
                    mode="external",
                ).allowed
            except RetrievalError as error:
                raise ToolExecutionError("Retrieval policy is invalid") from error

        result = refresh_registry(
            vault_root=vault_root,
            registry=registry,
            identity_allow_path=allowed,
        )
        visible_renamed = [
            (old_path, new_path)
            for old_path, new_path in result.renamed
            if allowed(old_path) and allowed(new_path)
        ]
        relocated_paths = [path for pair in visible_renamed for path in pair]
        changed_paths = [
            path for path in (*result.new, *result.modified, *result.deleted) if allowed(path)
        ]
        activity.append(
            tool="ingestion_registry_preflight",
            source_paths=[source_path],
            changed_paths=[*changed_paths, *relocated_paths],
        )

    policy_reads = build_policy_read_tools(
        vault_root=vault_root,
        activity=activity,
        invoke=runtime_scoped_invoke,
        runtime_dir=resolved_runtime_dir,
    )
    exploration = build_exploration_tools(
        vault_root=vault_root,
        activity=activity,
        invoke=runtime_scoped_invoke,
    )
    coherence = build_coherence_tools(
        vault_root=vault_root,
        activity=activity,
        invoke=runtime_scoped_invoke,
        runtime_dir=resolved_runtime_dir,
    )
    research = build_research_tools(
        vault_root=vault_root,
        runtime_dir=resolved_runtime_dir,
        registry=registry,
        activity=activity,
        invoke=runtime_scoped_invoke,
        authorizer=authorizer,
        refresh_for_ingestion=refresh_research_for_ingestion,
    )
    multi_source_ingestion = build_multi_source_ingestion_tools(
        vault_root=vault_root,
        runtime_dir=resolved_runtime_dir,
        registry=registry,
        activity=activity,
        invoke=runtime_scoped_invoke,
    )
    personal_patterns = build_personal_pattern_tools(
        vault_root=vault_root,
        activity=activity,
        invoke=runtime_scoped_invoke,
    )

    def wiki_search_tool(query: str, limit: int = 8) -> dict[str, object]:
        def op() -> dict[str, object]:
            result = search_wiki(
                vault_root=vault_root,
                request=WikiSearchRequest(query=query, limit=limit, mode="external"),
            )
            activity.append(
                tool="wiki_search",
                source_paths=[hit.path for hit in result.hits],
            )
            return serialize_authoritative_output(result, output_type=WikiSearchResult)

        result = runtime_scoped_invoke(op)
        assert isinstance(result, dict)
        return result

    wiki_search = _strict_tool(
        wiki_search_tool,
        name="wiki_search",
        description=WIKI_SEARCH_MCP_DESCRIPTION,
        title="Search durable wiki",
        output_type=WikiSearchResult,
    )
    core_tools = [
        tool
        for tool in core._tool_manager.list_tools()
        if tool.name not in _POLICY_READ_OVERRIDES and tool.name not in excluded_core_tools
    ]
    return FastMCP(
        "LifeOS",
        instructions=LIFEOS_MCP_INSTRUCTIONS,
        tools=[
            *core_tools,
            *policy_reads,
            *exploration,
            wiki_search,
            *multi_source_ingestion,
            *research,
            *personal_patterns,
            *coherence,
        ],
        host=host,
        port=port,
        transport_security=transport_security,
        stateless_http=stateless_http,
        json_response=json_response,
    )
