"""Canonical, provider-neutral knowledge conversation contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping

from lifeos.retrieval import RetrievalScope

CONVERSATION_SCHEMA_VERSION = 1
ConversationStatus = Literal["active", "archived"]
TurnState = Literal[
    "ready",
    "evidence-only",
    "no-results",
    "unavailable-provider",
    "timeout",
    "malformed-response",
    "cancelled",
    "degraded",
]
SupportKind = Literal["direct", "synthesis", "inference"]


class ConversationError(ValueError):
    def __init__(self, code: str, message: str, data: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = dict(data or {})


@dataclass(frozen=True, slots=True)
class ConversationEvidence:
    evidence_id: str
    path: str
    heading: str | None
    start_line: int
    end_line: int
    source_hash: str
    chunk_hash: str
    excerpt: str
    ranking: dict[str, float]
    support: SupportKind = "direct"
    stale: bool = False

    def __post_init__(self) -> None:
        if (
            not self.evidence_id
            or not self.path
            or self.start_line < 1
            or self.end_line < self.start_line
        ):
            raise ConversationError(
                "invalid_evidence", "Conversation evidence provenance is invalid."
            )
        if not self.source_hash.startswith("sha256:") or not self.chunk_hash.startswith("sha256:"):
            raise ConversationError("invalid_evidence", "Conversation evidence hashes are invalid.")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ConversationParagraph:
    text: str
    citations: tuple[str, ...]
    support: SupportKind

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ConversationError("invalid_answer", "Answer paragraphs must not be blank.")

    def to_dict(self) -> dict[str, object]:
        return {"text": self.text, "citations": list(self.citations), "support": self.support}


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    turn_id: str
    created_at: str
    query: str
    state: TurnState
    evidence: tuple[ConversationEvidence, ...] = ()
    answer: tuple[ConversationParagraph, ...] = ()
    explanation: str = ""
    provider_disclosure: dict[str, object] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.turn_id or not self.query.strip() or not self.created_at:
            raise ConversationError(
                "invalid_turn", "Conversation turn identity, query, and timestamp are required."
            )
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ConversationError(
                "duplicate_evidence", "A turn cannot contain duplicate evidence IDs."
            )
        unknown = sorted(
            {citation for paragraph in self.answer for citation in paragraph.citations}
            - evidence_ids
        )
        if unknown:
            raise ConversationError(
                "invalid_citation",
                "Answer cites evidence that is not part of the turn.",
                {"citations": unknown},
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "turn_id": self.turn_id,
            "created_at": self.created_at,
            "query": self.query,
            "state": self.state,
            "evidence": [item.to_dict() for item in self.evidence],
            "answer": [item.to_dict() for item in self.answer],
            "explanation": self.explanation,
            "provider_disclosure": self.provider_disclosure,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class ConversationMetadata:
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    status: ConversationStatus
    scope: RetrievalScope
    pinned_sources: tuple[str, ...] = ()
    excluded_sources: tuple[str, ...] = ()
    parent_conversation_id: str | None = None
    branch_from_turn_id: str | None = None
    schema_version: int = CONVERSATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CONVERSATION_SCHEMA_VERSION:
            raise ConversationError(
                "unsupported_schema", "Knowledge conversation schema is unsupported."
            )
        if not self.conversation_id.startswith("conv-") or not self.title.strip():
            raise ConversationError(
                "invalid_conversation", "Conversation identity and title are required."
            )
        if self.status not in {"active", "archived"}:
            raise ConversationError("invalid_status", "Conversation status is invalid.")

    def to_frontmatter(self, turns: tuple[ConversationTurn, ...]) -> dict[str, object]:
        return {
            "type": "knowledge-conversation",
            "conversation_schema": self.schema_version,
            "conversation_id": self.conversation_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "retrieval_scope": self.scope.to_dict(),
            "pinned_sources": list(self.pinned_sources),
            "excluded_sources": list(self.excluded_sources),
            "parent_conversation_id": self.parent_conversation_id,
            "branch_from_turn_id": self.branch_from_turn_id,
            "turns": [turn.to_dict() for turn in turns],
        }


@dataclass(frozen=True, slots=True)
class ConversationArtifact:
    relative_path: str
    content_hash: str
    metadata: ConversationMetadata
    turns: tuple[ConversationTurn, ...]
    human_body: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "content_hash": self.content_hash,
            "metadata": {
                **self.metadata.to_frontmatter(()),
                "turns": None,
            },
            "turns": [turn.to_dict() for turn in self.turns],
            "human_body": self.human_body,
        }


def scope_from_dict(value: Mapping[str, Any] | None) -> RetrievalScope:
    data = dict(value or {})
    tuple_fields = {
        "paths",
        "folders",
        "note_types",
        "tags",
        "sources",
        "excluded_paths",
        "pinned_paths",
    }
    normalized: dict[str, Any] = {}
    for key in RetrievalScope.__dataclass_fields__:
        if key not in data:
            continue
        raw = data[key]
        normalized[key] = tuple(str(item) for item in raw) if key in tuple_fields else raw
    try:
        return RetrievalScope(**normalized)
    except (TypeError, ValueError) as exc:
        raise ConversationError("invalid_scope", "Saved conversation scope is invalid.") from exc


def evidence_from_dict(value: Mapping[str, Any]) -> ConversationEvidence:
    try:
        return ConversationEvidence(
            evidence_id=str(value["evidence_id"]),
            path=str(value["path"]),
            heading=str(value["heading"]) if value.get("heading") is not None else None,
            start_line=int(value["start_line"]),
            end_line=int(value["end_line"]),
            source_hash=str(value["source_hash"]),
            chunk_hash=str(value["chunk_hash"]),
            excerpt=str(value.get("excerpt", "")),
            ranking={str(k): float(v) for k, v in dict(value.get("ranking", {})).items()},
            support=str(value.get("support", "direct")),  # type: ignore[arg-type]
            stale=bool(value.get("stale", False)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConversationError(
            "invalid_evidence", "Saved conversation evidence is malformed."
        ) from exc


def paragraph_from_dict(value: Mapping[str, Any]) -> ConversationParagraph:
    try:
        return ConversationParagraph(
            str(value["text"]),
            tuple(str(item) for item in value.get("citations", ())),
            str(value["support"]),  # type: ignore[arg-type]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConversationError("invalid_answer", "Saved answer paragraph is malformed.") from exc


def turn_from_dict(value: Mapping[str, Any]) -> ConversationTurn:
    try:
        evidence = tuple(evidence_from_dict(dict(item)) for item in value.get("evidence", ()))
        answer = tuple(paragraph_from_dict(dict(item)) for item in value.get("answer", ()))
        return ConversationTurn(
            str(value["turn_id"]),
            str(value["created_at"]),
            str(value["query"]),
            str(value["state"]),  # type: ignore[arg-type]
            evidence,
            answer,
            str(value.get("explanation", "")),
            dict(value.get("provider_disclosure", {})),
            tuple(str(item) for item in value.get("diagnostics", ())),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ConversationError):
            raise
        raise ConversationError("invalid_turn", "Saved conversation turn is malformed.") from exc
