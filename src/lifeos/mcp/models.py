"""Structured MCP output models matching facade result contracts."""

from typing import Literal, TypedDict


class ReadMarkdownMCPResult(TypedDict):
    vault_path: str
    markdown_body: str
    source_tags: list[str]
    source_topics: list[str]


class RegistryRefreshMCPResult(TypedDict):
    new: list[str]
    modified: list[str]
    unchanged: list[str]
    deleted: list[str]
    proposals_indexed: int


class CreateWikiProposalMCPResult(TypedDict):
    proposal_id: str
    proposal_path: str
    target_path: str
    status: Literal["draft"]


class UpdateWikiSectionProposalMCPResult(TypedDict):
    proposal_id: str
    proposal_path: str
    target_path: str
    heading: str
    status: Literal["draft"]


class CompoundWikiProposalMCPResult(TypedDict):
    proposal_id: str
    proposal_path: str
    create_target_path: str
    update_target_path: str
    heading: str
    status: Literal["draft"]


class SubmitProposalMCPResult(TypedDict):
    proposal_id: str
    status: Literal["pending"]
    review_digest: str


class ApproveProposalMCPResult(TypedDict):
    proposal_id: str
    status: Literal["approved"]
    review_digest: str


class ApplyProposalMCPResult(TypedDict):
    proposal_id: str
    status: Literal["applied"]
    changed_paths: list[str]


class WikiSearchHitMCPResult(TypedDict):
    path: str
    title: str
    description: str
    excerpt: str
    score: int


class WikiSearchMCPResult(TypedDict):
    query: str
    hits: list[WikiSearchHitMCPResult]


class EvolveWikiProposalMCPResult(TypedDict):
    proposal_id: str
    proposal_path: str
    target_paths: list[str]
    operation_count: int
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


class StudyLearningProposalMCPResult(TypedDict):
    proposal_id: str
    proposal_path: str
    target_paths: list[str]
    operation_count: int
    status: Literal["draft"]


class RuntimeActivityRecordMCPResult(TypedDict):
    timestamp: str
    tool: str
    focus_paths: list[str]
    instruction_ids: list[str]
    source_paths: list[str]
    proposal_id: str | None
    target_paths: list[str]
    changed_paths: list[str]
    operation_count: int | None


class RuntimeActivityMCPResult(TypedDict):
    records: list[RuntimeActivityRecordMCPResult]
