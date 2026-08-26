"""LifeOS MCP Server definition and tools."""

import logging
import posixpath
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import Tool
from pydantic import BaseModel, ConfigDict
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from lifeos.coherence import CoherenceError
from lifeos.coherence_scoped import runtime_exclusion_prefix
from lifeos.facade.consequential_tools import (
    APPLY_PROPOSAL_DESCRIPTOR,
    APPROVE_PROPOSAL_DESCRIPTOR,
    SUBMIT_PROPOSAL_DESCRIPTOR,
    SubmitProposalRequest,
    ApproveProposalRequest,
    ApplyProposalRequest,
    apply_proposal_tool,
    approve_proposal_tool,
    submit_proposal_tool,
)
from lifeos.facade.errors import (
    ToolAuthorizationError,
    ToolConflictError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolOwnershipConflictError,
    ToolRecoveryRequiredError,
    ToolUnavailableError,
    ToolValidationError,
)
from lifeos.facade.proposal_tools import (
    COMPOUND_WIKI_PROPOSAL_DESCRIPTOR,
    CREATE_WIKI_PROPOSAL_DESCRIPTOR,
    EVOLVE_WIKI_PROPOSAL_DESCRIPTOR,
    STUDY_EVOLVE_LEARNING_PROPOSAL_DESCRIPTOR,
    UPDATE_WIKI_SECTION_PROPOSAL_DESCRIPTOR,
    CompoundWikiProposalRequest,
    CreateWikiProposalRequest,
    EvolveWikiCreateRequest,
    EvolveWikiProposalRequest,
    EvolveWikiUpdateRequest,
    StudyFlashcardCreateRequest,
    EvolveStudyLearningProposalRequest,
    UpdateWikiSectionProposalRequest,
    create_wiki_and_update_section_proposal,
    create_wiki_proposal,
    evolve_wiki_proposal,
    evolve_study_learning_proposal,
    resolve_create_wiki_target,
    update_wiki_section_proposal,
)
from lifeos.facade.read_only import (
    READ_MARKDOWN_DESCRIPTOR,
    WIKI_SEARCH_DESCRIPTOR,
    VAULT_CONTEXT_DESCRIPTOR,
    ReadMarkdownRequest,
    WikiSearchRequest,
    VaultContextRequest,
    get_vault_context,
    read_markdown,
    search_wiki,
)
from lifeos.facade.registry_tools import (
    REGISTRY_REFRESH_DESCRIPTOR,
    refresh_registry,
)
from lifeos.facade.authorization import ConsequentialAuthorizer
from lifeos.mcp.models import (
    ApplyProposalMCPResult,
    ApproveProposalMCPResult,
    CompoundWikiProposalMCPResult,
    CreateWikiProposalMCPResult,
    EvolveWikiProposalMCPResult,
    ReadMarkdownMCPResult,
    RegistryRefreshMCPResult,
    SubmitProposalMCPResult,
    UpdateWikiSectionProposalMCPResult,
    WikiSearchMCPResult,
    VaultContextMCPResult,
    StudyLearningProposalMCPResult,
    RuntimeActivityMCPResult,
)
from lifeos.registry import Registry
from lifeos.retrieval import RetrievalError, RetrievalScope, scope_decision
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.runtime import ActivityStore
from lifeos.wiki.layout import WikiPageKind

logger = logging.getLogger(__name__)

T = TypeVar("T")


class EvolveWikiCreateMCPInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_path: str
    title: str
    body: str
    rationale: str
    tags: list[str] | None = None
    tag_rationale: str | None = None


class EvolveWikiUpdateMCPInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_path: str
    heading: str
    body: str
    rationale: str
    tags: list[str] | None = None
    tag_rationale: str | None = None


class StudyFlashcardCreateMCPInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_path: str
    card_id: str
    topic: str
    question: str
    answer: str
    rationale: str
    learning_context: str
    knowledge_refs: list[str] | None = None
    estimated_seconds: int = 30


LIFEOS_MCP_INSTRUCTIONS = (
    "LifeOS keeps user-owned Markdown canonical and constrains mutations rather than "
    "prescribing a universal semantic taxonomy. Application AGENTS.md governs LifeOS "
    "development; it is not the runtime contract. Use vault_context when goals, study "
    "purpose, journal context, experiments, or path-scoped system/instructions.yml rules "
    "could change how a source should be interpreted. Folder location supplies context, "
    "not permission: any registered canonical Markdown source may ground durable wiki "
    "evolution when relevant. Read the source, search existing durable knowledge with "
    "wiki_search, and read relevant hits before choosing mutations. Proposal-building "
    "ingestion tools automatically refresh the disposable registry immediately before source "
    "verification, so a separate registry_refresh call is not required for normal ingestion. "
    "Prefer reuse over creation and allow useful wiki folders to emerge from the vault. "
    "If no durable knowledge changes, create no proposal. Otherwise use "
    "ingestion_evolve_wiki_proposal for 1..12 reviewed wiki mutations. For a study/ source, "
    "use vault_context first when learning purpose matters; study_evolve_learning_proposal "
    "may combine selective flashcards with wiki evolution. Flashcard selection should reflect "
    "the inferred learning context, such as exam relevance, future prerequisites, conceptual "
    "leverage, mechanisms, or confusions, rather than generating cards for every fact. Do not "
    "generate flashcards from non-study sources by default. LifeOS verifies paths, hashes, "
    "ownership, provenance, operation bounds, review snapshots, and atomic application. Stop "
    "after draft unless the user explicitly requests an exact submit, approve, or apply "
    "transition. Never rewrite canonical notes directly when a proposal workflow exists. "
    "runtime_activity is read-only disposable diagnostics and contains routing metadata, not "
    "canonical note bodies."
)

REGISTRY_REFRESH_MCP_DESCRIPTION = (
    f"{REGISTRY_REFRESH_DESCRIPTOR.description} Use this explicit maintenance tool when "
    "derived indexes should be refreshed outside proposal-building ingestion; ingestion "
    "proposal tools refresh automatically. This writes only rebuildable registry data and "
    "does not change Markdown."
)
READ_MARKDOWN_MCP_DESCRIPTION = (
    f"{READ_MARKDOWN_DESCRIPTOR.description} Use this before ingestion to inspect the source "
    "and any relevant wiki notes; paths are vault-relative."
)
WIKI_SEARCH_MCP_DESCRIPTION = (
    f"{WIKI_SEARCH_DESCRIPTOR.description} Search after reading a source and before choosing "
    "wiki targets. Results are restricted to wiki/ and are read-only."
)
VAULT_CONTEXT_MCP_DESCRIPTION = (
    f"{VAULT_CONTEXT_DESCRIPTOR.description} Use explicit focus_paths for the source(s) the "
    "user is working with so path/domain instructions apply even when lexical search would "
    "not retrieve those files. This is read-only and grants no mutation authority."
)
STUDY_EVOLVE_LEARNING_MCP_DESCRIPTION = (
    f"{STUDY_EVOLVE_LEARNING_PROPOSAL_DESCRIPTOR.description} Use for a registered study/ "
    "source after gathering relevant vault context. LifeOS automatically refreshes the "
    "disposable registry before source verification, so new or edited study sources do not "
    "need a separate refresh call. The external agent chooses which facts merit retrieval "
    "practice for the inferred learning goal; LifeOS validates the bounded reviewed mutations. "
    "This creates only a draft."
)
RUNTIME_ACTIVITY_MCP_DESCRIPTION = (
    "Read recent disposable MCP routing/activity metadata for debugging. Records contain "
    "tool names, paths, instruction IDs, proposal IDs and counts, not canonical Markdown bodies."
)
EVOLVE_WIKI_PROPOSAL_MCP_DESCRIPTION = (
    f"{EVOLVE_WIKI_PROPOSAL_DESCRIPTOR.description} Prefer this after wiki_search and "
    "vault_read_markdown have inspected relevant existing knowledge. LifeOS automatically "
    "refreshes the disposable registry before source verification. Supply 1..12 distinct "
    "agent-selected wiki targets with a rationale for each create/update. Folder structure "
    "may emerge under wiki/; this creates only a draft and never applies it."
)
CREATE_WIKI_PROPOSAL_MCP_DESCRIPTION = (
    f"{CREATE_WIKI_PROPOSAL_DESCRIPTOR.description} Use after vault_read_markdown and "
    "supply a source-grounded title and body. LifeOS automatically refreshes the disposable "
    "registry before source verification. This is a compatibility single-create tool; "
    "explicit target_path is preferred here and page_kind+slug remains legacy-compatible. "
    "For new ingestion workflows prefer ingestion_evolve_wiki_proposal."
)
UPDATE_WIKI_SECTION_PROPOSAL_MCP_DESCRIPTION = (
    f"{UPDATE_WIKI_SECTION_PROPOSAL_DESCRIPTOR.description} Use after vault_read_markdown "
    "has inspected both the registered source and existing target. LifeOS automatically "
    "refreshes the disposable registry before source and target verification. Supply the "
    "exact heading text without # markers and only its replacement body. This creates a "
    "base-hash-bound, ownership-aware draft and does not modify the target wiki note."
)
COMPOUND_WIKI_PROPOSAL_MCP_DESCRIPTION = (
    f"{COMPOUND_WIKI_PROPOSAL_DESCRIPTOR.description} Use after vault_read_markdown has "
    "inspected both the source and existing update target. LifeOS automatically refreshes the "
    "disposable registry before source verification. Supply the absent create "
    "target with its grounded title and body, plus one exact heading and replacement body for "
    "the existing target. LifeOS selects the update operation from canonical ownership. This "
    "creates one atomic two-operation draft and does not modify either target."
)
SUBMIT_PROPOSAL_MCP_DESCRIPTION = (
    f"{SUBMIT_PROPOSAL_DESCRIPTOR.description} Call only when the user explicitly requests "
    "submission of that proposal."
)
APPROVE_PROPOSAL_MCP_DESCRIPTION = (
    f"{APPROVE_PROPOSAL_DESCRIPTOR.description} Call only when the user explicitly requests "
    "approval of that pending proposal."
)
APPLY_PROPOSAL_MCP_DESCRIPTION = (
    f"{APPLY_PROPOSAL_DESCRIPTOR.description} This changes canonical vault content; call "
    "only when the user explicitly requests application of that approved proposal."
)


def _strict_tool(
    fn: Callable[..., object],
    *,
    name: str,
    description: str,
    annotations: ToolAnnotations,
) -> Tool:
    tool = Tool.from_function(
        fn,
        name=name,
        description=description,
        annotations=annotations,
    )
    base_model = tool.fn_metadata.arg_model
    strict_model = cast(
        type[BaseModel],
        type(
            f"Strict{base_model.__name__}",
            (base_model,),
            {
                "model_config": ConfigDict(
                    arbitrary_types_allowed=True,
                    extra="forbid",
                )
            },
        ),
    )
    strict_model.model_rebuild()
    strict_metadata = tool.fn_metadata.model_copy(update={"arg_model": strict_model})
    return tool.model_copy(
        update={
            "fn_metadata": strict_metadata,
            "parameters": strict_model.model_json_schema(by_alias=True),
        }
    )


def _invoke_mcp_tool(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except ToolValidationError as error:
        raise ToolError("Invalid LifeOS tool arguments") from error
    except ToolNotFoundError as error:
        raise ToolError("Requested LifeOS object was not found") from error
    except ToolOwnershipConflictError as error:
        raise ToolError(str(error)) from error
    except ToolConflictError as error:
        raise ToolError("LifeOS operation conflicts with the current state") from error
    except ToolAuthorizationError as error:
        raise ToolError("Consequential operation was not authorized") from error
    except ToolRecoveryRequiredError as error:
        raise ToolError(
            "LifeOS recovery is required before proposal application can continue"
        ) from error
    except ToolUnavailableError as error:
        raise ToolError("Required LifeOS service is unavailable") from error
    except ToolExecutionError as error:
        raise ToolError(f"LifeOS operation failed: {error}") from error
    except Exception as error:
        logger.exception("Unexpected MCP tool failure")
        raise ToolError("Internal LifeOS error") from error


def create_mcp_server(
    *,
    vault_root: Path,
    registry: Registry,
    authorizer: ConsequentialAuthorizer,
    runtime_dir: Path | None = None,
) -> FastMCP:
    resolved_runtime_dir = runtime_dir or (vault_root / ".lifeos")
    activity = ActivityStore(resolved_runtime_dir)

    def _path_inside_runtime(path: str) -> bool:
        try:
            runtime_prefix = runtime_exclusion_prefix(
                vault_root,
                runtime_dir=resolved_runtime_dir,
            )
        except CoherenceError as error:
            raise ToolExecutionError("Could not resolve configured runtime directory") from error
        if runtime_prefix is None:
            return False
        normalized = posixpath.normpath(path)
        runtime_root = runtime_prefix.rstrip("/")
        return normalized == runtime_root or normalized.startswith(runtime_prefix)

    def _external_registry_identity_allow_path() -> Callable[[str], bool]:
        try:
            policy = load_retrieval_policy(vault_root)
        except RetrievalError as error:
            raise ToolExecutionError("Retrieval policy is invalid") from error
        scope = RetrievalScope()

        def allowed(path: str) -> bool:
            if path.startswith("conversations/") or path.startswith("proposals/"):
                return False
            if _path_inside_runtime(path):
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

        return allowed

    def _reject_runtime_paths(*paths: str | None) -> None:
        allow_path = _external_registry_identity_allow_path()
        denied = sorted({path for path in paths if path is not None and not allow_path(path)})
        if denied:
            raise ToolValidationError(
                "MCP ingestion paths are unavailable under the external retrieval policy"
            )

    def _visible_registry_paths(
        paths: tuple[str, ...],
        *,
        allow_path: Callable[[str], bool],
    ) -> list[str]:
        return [path for path in paths if allow_path(path)]

    def _visible_registry_renames(
        renames: tuple[tuple[str, str], ...],
        *,
        allow_path: Callable[[str], bool],
    ) -> list[tuple[str, str]]:
        return [
            (old_path, new_path)
            for old_path, new_path in renames
            if allow_path(old_path) and allow_path(new_path)
        ]

    def _refresh_for_ingestion(source_path: str) -> None:
        allow_identity = _external_registry_identity_allow_path()
        result = refresh_registry(
            vault_root=vault_root,
            registry=registry,
            identity_allow_path=allow_identity,
        )
        visible_renamed = _visible_registry_renames(result.renamed, allow_path=allow_identity)
        relocated_paths = [path for pair in visible_renamed for path in pair]
        activity.append(
            tool="ingestion_registry_preflight",
            source_paths=[source_path],
            changed_paths=[
                *_visible_registry_paths(result.new, allow_path=allow_identity),
                *_visible_registry_paths(result.modified, allow_path=allow_identity),
                *_visible_registry_paths(result.deleted, allow_path=allow_identity),
                *relocated_paths,
            ],
        )

    def registry_refresh_tool() -> RegistryRefreshMCPResult:
        def op() -> RegistryRefreshMCPResult:
            allow_identity = _external_registry_identity_allow_path()
            result = refresh_registry(
                vault_root=vault_root,
                registry=registry,
                identity_allow_path=allow_identity,
            )
            visible_new = _visible_registry_paths(result.new, allow_path=allow_identity)
            visible_modified = _visible_registry_paths(result.modified, allow_path=allow_identity)
            visible_unchanged = _visible_registry_paths(result.unchanged, allow_path=allow_identity)
            visible_deleted = _visible_registry_paths(result.deleted, allow_path=allow_identity)
            visible_renamed = _visible_registry_renames(result.renamed, allow_path=allow_identity)
            relocated_paths = [path for pair in visible_renamed for path in pair]
            activity.append(
                tool="registry_refresh",
                changed_paths=[
                    *visible_new,
                    *visible_modified,
                    *visible_deleted,
                    *relocated_paths,
                ],
            )
            payload: RegistryRefreshMCPResult = {
                "new": visible_new,
                "modified": visible_modified,
                "unchanged": visible_unchanged,
                "deleted": visible_deleted,
                "proposals_indexed": result.proposals_indexed,
            }
            if visible_renamed:
                payload["renamed"] = [
                    {"from_path": old_path, "to_path": new_path}
                    for old_path, new_path in visible_renamed
                ]
            return payload

        return _invoke_mcp_tool(op)

    def vault_read_markdown_tool(vault_path: str) -> ReadMarkdownMCPResult:
        def op() -> ReadMarkdownMCPResult:
            res = read_markdown(
                vault_root=vault_root, request=ReadMarkdownRequest(vault_path=vault_path)
            )
            activity.append(tool="vault_read_markdown", source_paths=[res.vault_path])
            return {
                "vault_path": res.vault_path,
                "markdown_body": res.markdown_body,
                "source_tags": list(res.source_tags),
                "source_topics": list(res.source_topics),
            }

        return _invoke_mcp_tool(op)

    def vault_context_tool(
        question: str, focus_paths: list[str] | None = None, limit: int = 8
    ) -> VaultContextMCPResult:
        def op() -> VaultContextMCPResult:
            pack = get_vault_context(
                vault_root=vault_root,
                request=VaultContextRequest(
                    question=question, focus_paths=tuple(focus_paths or ()), limit=limit
                ),
            )
            activity.append(
                tool="vault_context",
                focus_paths=list(focus_paths or ()),
                instruction_ids=[item.id for item in pack.instructions],
                source_paths=[item.path for item in pack.sources],
            )
            return {
                "question": pack.question,
                "instructions": [
                    {
                        "id": item.id,
                        "text": item.text,
                        "authority": item.authority,
                        "scope": item.scope,
                        "priority": item.priority,
                        "applicable_sources": list(item.applicable_sources),
                        "applicability": list(item.applicability),
                    }
                    for item in pack.instructions
                ],
                "sources": [
                    {
                        "path": item.path,
                        "title": item.title,
                        "description": item.description,
                        "excerpt": item.excerpt,
                        "score": item.score,
                    }
                    for item in pack.sources
                ],
                "evidence_gaps": list(pack.evidence_gaps),
                "omissions": list(pack.omissions),
                "diagnostics": [
                    {
                        "code": item.code,
                        "severity": item.severity,
                        "source_path": item.source_path,
                        "line": item.line,
                        "message": item.message,
                    }
                    for item in pack.diagnostics
                ],
            }

        return _invoke_mcp_tool(op)

    def wiki_search_tool(query: str, limit: int = 8) -> WikiSearchMCPResult:
        def op() -> WikiSearchMCPResult:
            result = search_wiki(
                vault_root=vault_root, request=WikiSearchRequest(query=query, limit=limit)
            )
            activity.append(tool="wiki_search", source_paths=[hit.path for hit in result.hits])
            return {
                "query": result.query,
                "hits": [
                    {
                        "path": hit.path,
                        "title": hit.title,
                        "description": hit.description,
                        "excerpt": hit.excerpt,
                        "score": hit.score,
                    }
                    for hit in result.hits
                ],
            }

        return _invoke_mcp_tool(op)

    def ingestion_evolve_wiki_proposal_tool(
        source_path: str,
        creates: list[EvolveWikiCreateMCPInput] | None = None,
        updates: list[EvolveWikiUpdateMCPInput] | None = None,
    ) -> EvolveWikiProposalMCPResult:
        def op() -> EvolveWikiProposalMCPResult:
            request = EvolveWikiProposalRequest(
                source_path=source_path,
                creates=tuple(
                    EvolveWikiCreateRequest(
                        target_path=item.target_path,
                        title=item.title,
                        body=item.body,
                        rationale=item.rationale,
                        tags=tuple(item.tags or ()),
                        tag_rationale=item.tag_rationale,
                    )
                    for item in creates or []
                ),
                updates=tuple(
                    EvolveWikiUpdateRequest(
                        target_path=item.target_path,
                        heading=item.heading,
                        body=item.body,
                        rationale=item.rationale,
                        tags=None if item.tags is None else tuple(item.tags),
                        tag_rationale=item.tag_rationale,
                    )
                    for item in updates or []
                ),
            )
            _reject_runtime_paths(
                request.source_path,
                *(item.target_path for item in request.creates),
                *(item.target_path for item in request.updates),
            )
            _refresh_for_ingestion(source_path)
            result = evolve_wiki_proposal(
                vault_root=vault_root,
                registry=registry,
                request=request,
                runtime_dir=resolved_runtime_dir,
            )
            activity.append(
                tool="ingestion_evolve_wiki_proposal",
                source_paths=[source_path],
                proposal_id=result.proposal_id,
                target_paths=list(result.target_paths),
                operation_count=result.operation_count,
            )
            return {
                "proposal_id": result.proposal_id,
                "proposal_path": result.proposal_path,
                "target_paths": list(result.target_paths),
                "operation_count": result.operation_count,
                "status": "draft",
            }

        return _invoke_mcp_tool(op)

    def study_evolve_learning_proposal_tool(
        source_path: str,
        wiki_creates: list[EvolveWikiCreateMCPInput] | None = None,
        wiki_updates: list[EvolveWikiUpdateMCPInput] | None = None,
        flashcards: list[StudyFlashcardCreateMCPInput] | None = None,
    ) -> StudyLearningProposalMCPResult:
        def op() -> StudyLearningProposalMCPResult:
            request = EvolveStudyLearningProposalRequest(
                source_path=source_path,
                wiki_creates=tuple(
                    EvolveWikiCreateRequest(
                        target_path=item.target_path,
                        title=item.title,
                        body=item.body,
                        rationale=item.rationale,
                        tags=tuple(item.tags or ()),
                        tag_rationale=item.tag_rationale,
                    )
                    for item in wiki_creates or []
                ),
                wiki_updates=tuple(
                    EvolveWikiUpdateRequest(
                        target_path=item.target_path,
                        heading=item.heading,
                        body=item.body,
                        rationale=item.rationale,
                        tags=None if item.tags is None else tuple(item.tags),
                        tag_rationale=item.tag_rationale,
                    )
                    for item in wiki_updates or []
                ),
                flashcards=tuple(
                    StudyFlashcardCreateRequest(
                        target_path=item.target_path,
                        card_id=item.card_id,
                        topic=item.topic,
                        question=item.question,
                        answer=item.answer,
                        rationale=item.rationale,
                        learning_context=item.learning_context,
                        knowledge_refs=tuple(item.knowledge_refs or ()),
                        estimated_seconds=item.estimated_seconds,
                    )
                    for item in flashcards or []
                ),
            )
            _reject_runtime_paths(
                request.source_path,
                *(item.target_path for item in request.wiki_creates),
                *(item.target_path for item in request.wiki_updates),
                *(item.target_path for item in request.flashcards),
                *(ref for item in request.flashcards for ref in item.knowledge_refs),
            )
            _refresh_for_ingestion(source_path)
            result = evolve_study_learning_proposal(
                vault_root=vault_root,
                registry=registry,
                request=request,
                runtime_dir=resolved_runtime_dir,
            )
            activity.append(
                tool="study_evolve_learning_proposal",
                source_paths=[source_path],
                proposal_id=result.proposal_id,
                target_paths=list(result.target_paths),
                operation_count=result.operation_count,
            )
            return {
                "proposal_id": result.proposal_id,
                "proposal_path": result.proposal_path,
                "target_paths": list(result.target_paths),
                "operation_count": result.operation_count,
                "status": "draft",
            }

        return _invoke_mcp_tool(op)

    def ingestion_create_wiki_proposal_tool(
        source_path: str,
        title: str,
        body: str,
        target_path: str | None = None,
        page_kind: WikiPageKind | None = None,
        slug: str | None = None,
        tags: list[str] | None = None,
        tag_rationale: str | None = None,
    ) -> CreateWikiProposalMCPResult:
        def op() -> CreateWikiProposalMCPResult:
            request = CreateWikiProposalRequest(
                source_path=source_path,
                target_path=target_path,
                title=title,
                body=body,
                tags=tuple(tags or ()),
                tag_rationale=tag_rationale,
                page_kind=page_kind,
                slug=slug,
            )
            resolved_target = resolve_create_wiki_target(
                target_path=request.target_path,
                page_kind=request.page_kind,
                slug=request.slug,
            )
            _reject_runtime_paths(request.source_path, resolved_target)
            _refresh_for_ingestion(source_path)
            res = create_wiki_proposal(
                vault_root=vault_root,
                registry=registry,
                request=request,
            )
            activity.append(
                tool="ingestion_create_wiki_proposal",
                source_paths=[source_path],
                proposal_id=res.proposal_id,
                target_paths=[res.target_path],
                operation_count=1,
            )
            return {
                "proposal_id": res.proposal_id,
                "proposal_path": res.proposal_path,
                "target_path": res.target_path,
                "status": "draft",
            }

        return _invoke_mcp_tool(op)

    def ingestion_update_wiki_section_proposal_tool(
        source_path: str,
        target_path: str,
        heading: str,
        body: str,
        tags: list[str] | None = None,
        tag_rationale: str | None = None,
    ) -> UpdateWikiSectionProposalMCPResult:
        def op() -> UpdateWikiSectionProposalMCPResult:
            request = UpdateWikiSectionProposalRequest(
                source_path=source_path,
                target_path=target_path,
                heading=heading,
                body=body,
                tags=None if tags is None else tuple(tags),
                tag_rationale=tag_rationale,
            )
            _reject_runtime_paths(request.source_path, request.target_path)
            _refresh_for_ingestion(source_path)
            res = update_wiki_section_proposal(
                vault_root=vault_root,
                registry=registry,
                request=request,
                runtime_dir=resolved_runtime_dir,
            )
            activity.append(
                tool="ingestion_update_wiki_section_proposal",
                source_paths=[source_path],
                proposal_id=res.proposal_id,
                target_paths=[res.target_path],
                operation_count=1,
            )
            return {
                "proposal_id": res.proposal_id,
                "proposal_path": res.proposal_path,
                "target_path": res.target_path,
                "heading": res.heading,
                "status": "draft",
            }

        return _invoke_mcp_tool(op)

    def ingestion_create_wiki_and_update_section_proposal_tool(
        source_path: str,
        create_title: str,
        create_body: str,
        update_target_path: str,
        update_heading: str,
        update_body: str,
        create_target_path: str | None = None,
        create_page_kind: WikiPageKind | None = None,
        create_slug: str | None = None,
        create_tags: list[str] | None = None,
        create_tag_rationale: str | None = None,
    ) -> CompoundWikiProposalMCPResult:
        def op() -> CompoundWikiProposalMCPResult:
            request = CompoundWikiProposalRequest(
                source_path=source_path,
                create_target_path=create_target_path,
                create_title=create_title,
                create_body=create_body,
                update_target_path=update_target_path,
                update_heading=update_heading,
                update_body=update_body,
                create_tags=tuple(create_tags or ()),
                create_tag_rationale=create_tag_rationale,
                create_page_kind=create_page_kind,
                create_slug=create_slug,
            )
            resolved_create_target = resolve_create_wiki_target(
                target_path=request.create_target_path,
                page_kind=request.create_page_kind,
                slug=request.create_slug,
            )
            _reject_runtime_paths(
                request.source_path,
                resolved_create_target,
                request.update_target_path,
            )
            _refresh_for_ingestion(source_path)
            res = create_wiki_and_update_section_proposal(
                vault_root=vault_root,
                registry=registry,
                request=request,
                runtime_dir=resolved_runtime_dir,
            )
            activity.append(
                tool="ingestion_create_wiki_and_update_section_proposal",
                source_paths=[source_path],
                proposal_id=res.proposal_id,
                target_paths=[res.create_target_path, res.update_target_path],
                operation_count=2,
            )
            return {
                "proposal_id": res.proposal_id,
                "proposal_path": res.proposal_path,
                "create_target_path": res.create_target_path,
                "update_target_path": res.update_target_path,
                "heading": res.heading,
                "status": "draft",
            }

        return _invoke_mcp_tool(op)

    def proposal_submit_tool(proposal_id: str) -> SubmitProposalMCPResult:
        def op() -> SubmitProposalMCPResult:
            res = submit_proposal_tool(
                vault_root=vault_root,
                authorizer=authorizer,
                request=SubmitProposalRequest(proposal_id=proposal_id),
            )
            activity.append(tool="proposal_submit", proposal_id=res.proposal_id)
            return {
                "proposal_id": res.proposal_id,
                "status": "pending",
                "review_digest": res.review_digest,
            }

        return _invoke_mcp_tool(op)

    def proposal_approve_tool(proposal_id: str) -> ApproveProposalMCPResult:
        def op() -> ApproveProposalMCPResult:
            res = approve_proposal_tool(
                vault_root=vault_root,
                authorizer=authorizer,
                request=ApproveProposalRequest(proposal_id=proposal_id),
            )
            activity.append(tool="proposal_approve", proposal_id=res.proposal_id)
            return {
                "proposal_id": res.proposal_id,
                "status": "approved",
                "review_digest": res.review_digest,
            }

        return _invoke_mcp_tool(op)

    def proposal_apply_tool(proposal_id: str) -> ApplyProposalMCPResult:
        def op() -> ApplyProposalMCPResult:
            if runtime_dir is None:
                res = apply_proposal_tool(
                    vault_root=vault_root,
                    authorizer=authorizer,
                    request=ApplyProposalRequest(proposal_id=proposal_id),
                )
            else:
                res = apply_proposal_tool(
                    vault_root=vault_root,
                    authorizer=authorizer,
                    request=ApplyProposalRequest(proposal_id=proposal_id),
                    identity_runtime_dir=runtime_dir,
                )
            activity.append(
                tool="proposal_apply",
                proposal_id=res.proposal_id,
                changed_paths=list(res.changed_paths),
            )
            return {
                "proposal_id": res.proposal_id,
                "status": "applied",
                "changed_paths": list(res.changed_paths),
            }

        return _invoke_mcp_tool(op)

    def runtime_activity_tool(limit: int = 20) -> RuntimeActivityMCPResult:
        try:
            records = activity.read(limit=limit)
        except ValueError as error:
            raise ToolError("Invalid LifeOS tool arguments") from error
        return {
            "records": [
                {
                    "timestamp": item.timestamp,
                    "tool": item.tool,
                    "focus_paths": list(item.focus_paths),
                    "instruction_ids": list(item.instruction_ids),
                    "source_paths": list(item.source_paths),
                    "proposal_id": item.proposal_id,
                    "target_paths": list(item.target_paths),
                    "changed_paths": list(item.changed_paths),
                    "operation_count": item.operation_count,
                }
                for item in records
            ]
        }

    return FastMCP(
        "LifeOS",
        instructions=LIFEOS_MCP_INSTRUCTIONS,
        tools=[
            _strict_tool(
                registry_refresh_tool,
                name="registry_refresh",
                description=REGISTRY_REFRESH_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Refresh LifeOS registry",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            ),
            _strict_tool(
                vault_read_markdown_tool,
                name="vault_read_markdown",
                description=READ_MARKDOWN_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Read vault Markdown",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            ),
            _strict_tool(
                vault_context_tool,
                name="vault_context",
                description=VAULT_CONTEXT_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Build vault context",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            ),
            _strict_tool(
                wiki_search_tool,
                name="wiki_search",
                description=WIKI_SEARCH_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Search wiki knowledge",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            ),
            _strict_tool(
                ingestion_evolve_wiki_proposal_tool,
                name="ingestion_evolve_wiki_proposal",
                description=EVOLVE_WIKI_PROPOSAL_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Evolve wiki knowledge",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
            ),
            _strict_tool(
                study_evolve_learning_proposal_tool,
                name="study_evolve_learning_proposal",
                description=STUDY_EVOLVE_LEARNING_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Evolve study learning",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
            ),
            _strict_tool(
                ingestion_create_wiki_proposal_tool,
                name="ingestion_create_wiki_proposal",
                description=CREATE_WIKI_PROPOSAL_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Create wiki ingestion proposal",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
            ),
            _strict_tool(
                ingestion_update_wiki_section_proposal_tool,
                name="ingestion_update_wiki_section_proposal",
                description=UPDATE_WIKI_SECTION_PROPOSAL_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Update wiki section ingestion proposal",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
            ),
            _strict_tool(
                ingestion_create_wiki_and_update_section_proposal_tool,
                name="ingestion_create_wiki_and_update_section_proposal",
                description=COMPOUND_WIKI_PROPOSAL_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Create wiki and update section ingestion proposal",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
            ),
            _strict_tool(
                runtime_activity_tool,
                name="runtime_activity",
                description=RUNTIME_ACTIVITY_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Inspect LifeOS runtime activity",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            ),
            _strict_tool(
                proposal_submit_tool,
                name="proposal_submit",
                description=SUBMIT_PROPOSAL_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Submit proposal",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
            ),
            _strict_tool(
                proposal_approve_tool,
                name="proposal_approve",
                description=APPROVE_PROPOSAL_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Approve proposal",
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
            ),
            _strict_tool(
                proposal_apply_tool,
                name="proposal_apply",
                description=APPLY_PROPOSAL_MCP_DESCRIPTION,
                annotations=ToolAnnotations(
                    title="Apply proposal",
                    readOnlyHint=False,
                    destructiveHint=True,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
            ),
        ],
    )
