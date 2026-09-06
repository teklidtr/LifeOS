"""Structured MCP output models matching transport-specific result contracts."""

from typing import Literal

from typing_extensions import NotRequired, TypedDict


class ReadMarkdownMCPResult(TypedDict):
    vault_path: str
    markdown_body: str
    source_tags: list[str]
    source_topics: list[str]


class VaultSearchHitMCPResult(TypedDict):
    path: str
    title: str
    description: str
    excerpt: str
    score: int
    matched_terms: list[str]


class VaultDiagnosticMCPResult(TypedDict):
    code: str
    severity: str
    source_path: str
    line: int
    message: str


class VaultSearchMCPResult(TypedDict):
    query: str
    hits: list[VaultSearchHitMCPResult]
    diagnostics: list[VaultDiagnosticMCPResult]


class VaultLinkMCPResult(TypedDict):
    source_path: str
    target_path: str
    target_heading: str | None
    direction: Literal["outgoing", "backlink"]


class VaultLinksMCPResult(TypedDict):
    path: str
    links: list[VaultLinkMCPResult]
    truncated: bool
    next_offset: int | None
    diagnostics: list[VaultDiagnosticMCPResult]


class RegistryRenameMCPResult(TypedDict):
    from_path: str
    to_path: str


class RegistryRefreshMCPResult(TypedDict):
    new: list[str]
    modified: list[str]
    unchanged: list[str]
    deleted: list[str]
    renamed: NotRequired[list[RegistryRenameMCPResult] | None]
    proposals_indexed: int


class ResearchContextSourceMCPResult(TypedDict):
    path: str
    title: str
    description: str
    excerpt: str
    score: int


class ResearchQueryContextMCPResult(TypedDict):
    query: str
    context_sources: list[ResearchContextSourceMCPResult]
    wiki_hits: list[ResearchContextSourceMCPResult]
    evidence_gaps: list[str]
    omissions: list[str]
    persistence: Literal["none"]
    decision_authority: Literal["external-agent"]


class CreateWikiProposalMCPResult(TypedDict):
    """Research synthesis transport contract; facade status is intentionally broader."""

    proposal_id: str
    proposal_path: str
    target_path: str
    status: Literal["draft"]


class VaultContextInstructionMCPResult(TypedDict):
    id: str
    text: str
    authority: str
    scope: str
    priority: int
    applicable_sources: list[str]
    applicability: list[str]


class VaultContextSourceMCPResult(TypedDict):
    path: str
    title: str
    description: str
    excerpt: str
    score: int
    retrieval_mode: NotRequired[str]
    retrieval_reasons: NotRequired[list[str]]
    ranking: NotRequired[dict[str, float]]
    duplicate_paths: NotRequired[list[str]]


class VaultContextDiagnosticMCPResult(TypedDict):
    code: str
    severity: str
    source_path: str
    line: int
    message: str


class VaultContextMCPResult(TypedDict):
    question: str
    instructions: list[VaultContextInstructionMCPResult]
    sources: list[VaultContextSourceMCPResult]
    evidence_gaps: list[str]
    omissions: list[str]
    diagnostics: list[VaultContextDiagnosticMCPResult]


class RuntimeActivityRecordMCPResult(TypedDict):
    timestamp: str
    tool: str
    actor_id: NotRequired[str | None]
    focus_paths: list[str]
    instruction_ids: list[str]
    source_paths: list[str]
    proposal_id: str | None
    target_paths: list[str]
    changed_paths: list[str]
    operation_count: int | None


class RuntimeActivityMCPResult(TypedDict):
    records: list[RuntimeActivityRecordMCPResult]
