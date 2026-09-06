"""MCP surface for target-reconciled multi-source ingestion."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

from lifeos.coherence import CoherenceError
from lifeos.coherence_scoped import runtime_exclusion_prefix
from lifeos.facade.errors import ToolExecutionError, ToolValidationError
from lifeos.facade.multi_source_ingestion import (
    EVOLVE_WIKI_BATCH_PROPOSAL_DESCRIPTOR,
    BatchSourceSnapshotRequest,
    BatchWikiCreateRequest,
    BatchWikiSectionRequest,
    BatchWikiUpdateRequest,
    EvolveWikiBatchProposalRequest,
    evolve_wiki_batch_proposal,
)
from lifeos.facade.registry_tools import refresh_registry
from lifeos.mcp.activity_store import MCPActivityStore
from lifeos.mcp.models import EvolveWikiProposalMCPResult
from lifeos.mcp.tool_contracts import build_mcp_tool
from lifeos.registry import Registry
from lifeos.retrieval import RetrievalError, RetrievalScope, scope_decision
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.runtime_scope import build_runtime_exclusion_matcher


class BatchSourceSnapshotMCPInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    content_hash: str


class BatchWikiSectionMCPInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heading: str
    body: str


class BatchWikiCreateMCPInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_path: str
    title: str
    body: str
    rationale: str
    source_paths: list[str]
    tags: list[str] | None = None
    tag_rationale: str | None = None


class BatchWikiUpdateMCPInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_path: str
    sections: list[BatchWikiSectionMCPInput]
    rationale: str
    source_paths: list[str]
    tags: list[str] | None = None
    tag_rationale: str | None = None


EVOLVE_WIKI_BATCH_MCP_DESCRIPTION = (
    f"{EVOLVE_WIKI_BATCH_PROPOSAL_DESCRIPTOR.description} Jointly read the selected sources, "
    "inspect vault context and existing wiki knowledge, then reconcile desired changes by target. "
    "Pass the exact path/content_hash snapshots returned by vault_read_many so a registry refresh "
    "cannot silently advance the evidence version used for synthesis. Each target appears once and "
    "names only its relevant source subset. One human-owned target may include several exact "
    "section replacements in one file-level patch. Limits are 64 distinct sources, 32 distinct "
    "targets, and 2 MiB canonical patch plus immutable review payload. Oversized batches fail "
    "without automatic fan-out. This creates one draft only; when joint reasoning finds zero "
    "durable changes, do not call this tool."
)


def _proposal_tool(fn: Callable[..., object]) -> Tool:
    return build_mcp_tool(
        fn,
        name="ingestion_evolve_wiki_batch_proposal",
        description=EVOLVE_WIKI_BATCH_MCP_DESCRIPTION,
        annotations=ToolAnnotations(
            title="Reconcile a multi-source wiki batch",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        strict_inputs=True,
    )


def build_multi_source_ingestion_tools(
    *,
    vault_root: Path,
    runtime_dir: Path,
    registry: Registry,
    activity: MCPActivityStore,
    invoke: Callable[[Callable[[], object]], object],
) -> list[Tool]:
    def external_allow_path() -> Callable[[str], bool]:
        try:
            runtime_prefix = runtime_exclusion_prefix(vault_root, runtime_dir=runtime_dir)
            runtime_excluded = build_runtime_exclusion_matcher(
                vault_root, runtime_dir=runtime_dir, snapshot_prefix=runtime_prefix
            )
            policy = load_retrieval_policy(vault_root)
        except (CoherenceError, RetrievalError) as error:
            raise ToolExecutionError("Could not resolve external ingestion policy") from error
        scope = RetrievalScope()

        def allowed(path: str) -> bool:
            if path.startswith("conversations/") or path.startswith("proposals/"):
                return False
            try:
                if runtime_excluded(path):
                    return False
                return scope_decision(path, scope=scope, policy=policy, mode="external").allowed
            except (CoherenceError, RetrievalError) as error:
                raise ToolExecutionError("Could not verify external ingestion path") from error

        return allowed

    def refresh_batch(source_paths: tuple[str, ...]) -> None:
        allowed = external_allow_path()
        result = refresh_registry(
            vault_root=vault_root, registry=registry, identity_allow_path=allowed
        )
        renamed = [
            (old_path, new_path)
            for old_path, new_path in result.renamed
            if allowed(old_path) and allowed(new_path)
        ]
        activity.append(
            tool="ingestion_registry_preflight",
            source_paths=list(source_paths),
            changed_paths=[
                *[
                    path
                    for path in (*result.new, *result.modified, *result.deleted)
                    if allowed(path)
                ],
                *[path for pair in renamed for path in pair],
            ],
        )

    def ingestion_evolve_wiki_batch_proposal_tool(
        source_snapshots: list[BatchSourceSnapshotMCPInput],
        creates: list[BatchWikiCreateMCPInput] | None = None,
        updates: list[BatchWikiUpdateMCPInput] | None = None,
    ) -> EvolveWikiProposalMCPResult:
        def op() -> EvolveWikiProposalMCPResult:
            request = EvolveWikiBatchProposalRequest(
                source_snapshots=tuple(
                    BatchSourceSnapshotRequest(
                        path=item.path,
                        content_hash=item.content_hash,
                    )
                    for item in source_snapshots
                ),
                creates=tuple(
                    BatchWikiCreateRequest(
                        target_path=item.target_path,
                        title=item.title,
                        body=item.body,
                        rationale=item.rationale,
                        source_paths=tuple(item.source_paths),
                        tags=tuple(item.tags or ()),
                        tag_rationale=item.tag_rationale,
                    )
                    for item in creates or []
                ),
                updates=tuple(
                    BatchWikiUpdateRequest(
                        target_path=item.target_path,
                        sections=tuple(
                            BatchWikiSectionRequest(heading=section.heading, body=section.body)
                            for section in item.sections
                        ),
                        rationale=item.rationale,
                        source_paths=tuple(item.source_paths),
                        tags=None if item.tags is None else tuple(item.tags),
                        tag_rationale=item.tag_rationale,
                    )
                    for item in updates or []
                ),
            )
            allowed = external_allow_path()
            all_paths = [
                *request.source_paths,
                *(item.target_path for item in request.creates),
                *(item.target_path for item in request.updates),
            ]
            if any(not allowed(path) for path in all_paths):
                raise ToolValidationError(
                    "MCP batch paths are unavailable under the external retrieval policy"
                )
            refresh_batch(request.source_paths)
            result = evolve_wiki_batch_proposal(
                vault_root=vault_root,
                registry=registry,
                request=request,
                runtime_dir=runtime_dir,
            )
            activity.append(
                tool="ingestion_evolve_wiki_batch_proposal",
                source_paths=list(request.source_paths),
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

        return cast(EvolveWikiProposalMCPResult, invoke(op))

    return [_proposal_tool(ingestion_evolve_wiki_batch_proposal_tool)]
