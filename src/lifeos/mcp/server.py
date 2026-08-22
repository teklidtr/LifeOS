"""LifeOS MCP Server definition and tools."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import Tool
from pydantic import BaseModel, ConfigDict
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

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
    ToolRecoveryRequiredError,
    ToolUnavailableError,
    ToolValidationError,
)
from lifeos.facade.proposal_tools import (
    CREATE_WIKI_PROPOSAL_DESCRIPTOR,
    CreateWikiProposalRequest,
    create_wiki_proposal,
)
from lifeos.facade.read_only import READ_MARKDOWN_DESCRIPTOR, ReadMarkdownRequest, read_markdown
from lifeos.facade.registry_tools import (
    REGISTRY_REFRESH_DESCRIPTOR,
    refresh_registry,
)
from lifeos.facade.authorization import ConsequentialAuthorizer
from lifeos.mcp.models import (
    ApplyProposalMCPResult,
    ApproveProposalMCPResult,
    CreateWikiProposalMCPResult,
    ReadMarkdownMCPResult,
    RegistryRefreshMCPResult,
    SubmitProposalMCPResult,
)
from lifeos.registry import Registry

logger = logging.getLogger(__name__)

T = TypeVar("T")

LIFEOS_MCP_INSTRUCTIONS = (
    "LifeOS keeps Markdown canonical. For ingestion requests, first call registry_refresh "
    "to register the source's current path and hash, then call vault_read_markdown, "
    "synthesize a grounded title and body "
    "from that content, then call ingestion_create_wiki_proposal. Stop after the draft "
    "proposal unless the user explicitly requests another exact lifecycle transition. "
    "Never call proposal_submit, proposal_approve, or proposal_apply merely because an "
    "ingestion was requested. Use vault-relative paths and never directly rewrite "
    "canonical notes."
)

REGISTRY_REFRESH_MCP_DESCRIPTION = (
    f"{REGISTRY_REFRESH_DESCRIPTOR.description} Use after files are added, changed, moved, "
    "or deleted. This writes only rebuildable registry data and does not change Markdown."
)

READ_MARKDOWN_MCP_DESCRIPTION = (
    f"{READ_MARKDOWN_DESCRIPTOR.description} Use this before ingestion to inspect the "
    "registered source; paths are vault-relative."
)
CREATE_WIKI_PROPOSAL_MCP_DESCRIPTION = (
    f"{CREATE_WIKI_PROPOSAL_DESCRIPTOR.description} Use after vault_read_markdown and "
    "supply a source-grounded title and body. This creates a draft and does not modify "
    "the target wiki note."
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
    *, vault_root: Path, registry: Registry, authorizer: ConsequentialAuthorizer
) -> FastMCP:
    def registry_refresh_tool() -> RegistryRefreshMCPResult:
        def op() -> RegistryRefreshMCPResult:
            result = refresh_registry(vault_root=vault_root, registry=registry)
            return {
                "new": list(result.new),
                "modified": list(result.modified),
                "unchanged": list(result.unchanged),
                "deleted": list(result.deleted),
                "proposals_indexed": result.proposals_indexed,
            }

        return _invoke_mcp_tool(op)

    def vault_read_markdown_tool(vault_path: str) -> ReadMarkdownMCPResult:
        def op() -> ReadMarkdownMCPResult:
            res = read_markdown(
                vault_root=vault_root, request=ReadMarkdownRequest(vault_path=vault_path)
            )
            return {"vault_path": res.vault_path, "markdown_body": res.markdown_body}

        return _invoke_mcp_tool(op)

    def ingestion_create_wiki_proposal_tool(
        source_path: str, target_path: str, title: str, body: str
    ) -> CreateWikiProposalMCPResult:
        def op() -> CreateWikiProposalMCPResult:
            res = create_wiki_proposal(
                vault_root=vault_root,
                registry=registry,
                request=CreateWikiProposalRequest(
                    source_path=source_path,
                    target_path=target_path,
                    title=title,
                    body=body,
                ),
            )
            return {
                "proposal_id": res.proposal_id,
                "proposal_path": res.proposal_path,
                "target_path": res.target_path,
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
            return {
                "proposal_id": res.proposal_id,
                "status": "approved",
                "review_digest": res.review_digest,
            }

        return _invoke_mcp_tool(op)

    def proposal_apply_tool(proposal_id: str) -> ApplyProposalMCPResult:
        def op() -> ApplyProposalMCPResult:
            res = apply_proposal_tool(
                vault_root=vault_root,
                authorizer=authorizer,
                request=ApplyProposalRequest(proposal_id=proposal_id),
            )
            return {
                "proposal_id": res.proposal_id,
                "status": "applied",
                "changed_paths": list(res.changed_paths),
            }

        return _invoke_mcp_tool(op)

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
