"""Structured MCP output models matching facade result contracts."""

from typing import Literal, TypedDict


class ReadMarkdownMCPResult(TypedDict):
    vault_path: str
    markdown_body: str


class CreateWikiProposalMCPResult(TypedDict):
    proposal_id: str
    proposal_path: str
    target_path: str
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
