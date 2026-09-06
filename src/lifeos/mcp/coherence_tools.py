"""Read-only MCP surface for canonical note identity and current location."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypedDict, cast

from mcp.server.fastmcp.tools import Tool

from lifeos.coherence import CoherenceError
from lifeos.coherence_scoped import collect_scoped_identity_snapshot
from lifeos.facade.errors import ToolExecutionError, ToolNotFoundError, ToolValidationError
from lifeos.mcp.exploration_tools import _strict_tool
from lifeos.registry.file_tracking import FileTrackingError, validate_vault_path
from lifeos.retrieval import RetrievalError, RetrievalScope, scope_decision
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.runtime import ActivityStore
from lifeos.vault import is_markdown_path

Invoke = Callable[[Callable[[], object]], object]


class NoteIdentityMCPResult(TypedDict):
    stable_id: str | None
    current_path: str
    content_hash: str
    relocation_safe: bool


NOTE_IDENTITY_MCP_DESCRIPTION = (
    "Resolve one current canonical Markdown path to its durable frontmatter id, current path, "
    "and content hash. Stable id, path, and content version are separate facts. This tool is "
    "read-only, follows the external retrieval policy, and fails closed when a stable id is "
    "duplicated or ambiguous within the caller-visible scope."
)


def build_coherence_tools(
    *,
    vault_root: Path,
    activity: ActivityStore,
    invoke: Invoke,
    runtime_dir: Path | None = None,
) -> tuple[Tool, ...]:
    """Build the provider-neutral identity lookup used by relocation-aware agents."""

    def vault_note_identity_tool(
        vault_path: str,
        allow_protected: bool = False,
    ) -> NoteIdentityMCPResult:
        def op() -> NoteIdentityMCPResult:
            try:
                validate_vault_path(vault_path)
            except FileTrackingError as exc:
                raise ToolValidationError("Invalid vault path") from exc
            if not is_markdown_path(vault_path):
                raise ToolValidationError("Only Markdown files have canonical note identity")

            scope = RetrievalScope(allow_protected=allow_protected)
            try:
                policy = load_retrieval_policy(vault_root)
                decision = scope_decision(
                    vault_path,
                    scope=scope,
                    policy=policy,
                    mode="external",
                )
            except RetrievalError as exc:
                raise ToolExecutionError("Retrieval policy is invalid") from exc
            if not decision.allowed:
                raise ToolValidationError(
                    f"Vault path is not available for retrieval: {decision.reason}"
                )

            try:
                snapshot = collect_scoped_identity_snapshot(
                    vault_root,
                    allow_path=lambda path: (
                        scope_decision(
                            path,
                            scope=scope,
                            policy=policy,
                            mode="external",
                        ).allowed
                    ),
                    runtime_dir=runtime_dir,
                )
            except (CoherenceError, RetrievalError) as exc:
                raise ToolExecutionError("Could not rebuild authorized note identity") from exc

            note = snapshot.by_path(vault_path)
            if note is None:
                raise ToolNotFoundError("Canonical Markdown note is missing")
            if note.stable_id is not None and len(snapshot.by_stable_id(note.stable_id)) != 1:
                raise ToolValidationError("Stable note id is duplicated or ambiguous")
            activity.append(tool="vault_note_identity", source_paths=[note.path])
            return {
                "stable_id": note.stable_id,
                "current_path": note.path,
                "content_hash": note.content_hash,
                "relocation_safe": note.relocation_safe,
            }

        return cast(NoteIdentityMCPResult, invoke(op))

    return (
        _strict_tool(
            vault_note_identity_tool,
            name="vault_note_identity",
            description=NOTE_IDENTITY_MCP_DESCRIPTION,
            title="Resolve vault note identity",
        ),
    )
