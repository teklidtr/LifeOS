"""Canonical Markdown persistence for knowledge conversations."""

from __future__ import annotations

import re
import secrets
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import yaml

from lifeos.daily.service import _atomic_write, content_hash
from lifeos.markdown.parser import parse_markdown_note, replace_managed_block, splice_managed_block
from lifeos.retrieval import RetrievalScope
from lifeos.vault import (
    VaultAccessError,
    VaultMarkdownFile,
    iter_vault_markdown,
    read_vault_markdown,
)

from .contracts import (
    CONVERSATION_SCHEMA_VERSION,
    ConversationArtifact,
    ConversationError,
    ConversationMetadata,
    ConversationTurn,
    scope_from_dict,
    turn_from_dict,
)

_MANAGED_START = "<!-- lifeos:managed:start knowledge-conversation -->"
_MANAGED_END = "<!-- lifeos:managed:end knowledge-conversation -->"
_ID_RE = re.compile(r"^conv-(\d{8}T\d{6}Z)-[a-f0-9]{8}$")


def _now(value: datetime | None = None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ConversationError(
            "invalid_timestamp", "Conversation timestamps must be timezone-aware."
        )
    return moment.astimezone(timezone.utc)


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return result[:64] or "conversation"


def _conversation_id(moment: datetime) -> str:
    return f"conv-{moment.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"


def _path(metadata: ConversationMetadata) -> str:
    match = _ID_RE.fullmatch(metadata.conversation_id)
    if match is None:
        raise ConversationError("invalid_conversation", "Conversation ID is malformed.")
    year = match.group(1)[:4]
    return f"conversations/{year}/{_slug(metadata.title)}-{metadata.conversation_id}.md"


def _render_turn(turn: ConversationTurn) -> str:
    lines = [
        f"## Turn {turn.turn_id}",
        "",
        f"**Question:** {turn.query}",
        "",
        f"**State:** `{turn.state}`",
    ]
    if turn.evidence:
        lines.extend(["", "### Evidence"])
        for item in turn.evidence:
            target = f"{item.path}#{item.heading}" if item.heading else item.path
            lines.extend(
                [
                    "",
                    f"- `{item.evidence_id}` · [[{target}]] · lines {item.start_line}-{item.end_line}",
                    f"  - {item.excerpt.strip()}",
                ]
            )
    if turn.answer:
        lines.extend(["", "### Answer"])
        for paragraph in turn.answer:
            citations = " ".join(f"[{citation}]" for citation in paragraph.citations)
            lines.extend(
                [
                    "",
                    f"{paragraph.text} {citations}".rstrip(),
                    "",
                    f"_Support: {paragraph.support}_",
                ]
            )
    if turn.explanation:
        lines.extend(["", f"_Explanation: {turn.explanation}_"])
    return "\n".join(lines).rstrip()


def _managed_body(turns: tuple[ConversationTurn, ...]) -> str:
    content = (
        "\n\n".join(_render_turn(turn) for turn in turns)
        if turns
        else "No questions have been asked yet."
    )
    return f"{_MANAGED_START}\n# Knowledge conversation\n\n{content}\n{_MANAGED_END}"


def _document(
    metadata: ConversationMetadata, turns: tuple[ConversationTurn, ...], human_body: str
) -> str:
    frontmatter = metadata.to_frontmatter(turns)
    dumped = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip()
    annotations = human_body.strip("\n") or "## Annotations\n\n"
    return f"---\n{dumped}\n---\n\n{_managed_body(turns)}\n\n{annotations}\n"


def _read_source(vault_root: Path, relative_path: str) -> VaultMarkdownFile:
    try:
        return read_vault_markdown(vault_root, relative_path)
    except VaultAccessError as exc:
        raise ConversationError(exc.code, str(exc), {"path": relative_path}) from exc


def _parse(source_path: Path, relative_path: str, content: str) -> ConversationArtifact:
    parsed = parse_markdown_note(source_path, content=content)
    error = next((item for item in parsed.findings if item.severity == "error"), None)
    if error is not None:
        raise ConversationError("malformed_artifact", error.message, {"path": relative_path})
    fm = dict(parsed.frontmatter)
    if fm.get("type") != "knowledge-conversation":
        raise ConversationError("unsupported_artifact", "The note is not a knowledge conversation.")
    try:
        schema = int(fm.get("conversation_schema", 0))
    except (TypeError, ValueError) as exc:
        raise ConversationError("unsupported_schema", "Conversation schema is malformed.") from exc
    if schema != CONVERSATION_SCHEMA_VERSION:
        raise ConversationError("unsupported_schema", "Conversation schema version is unsupported.")
    matches = [block for block in parsed.managed_blocks if block.name == "knowledge-conversation"]
    if len(matches) != 1 or len(parsed.managed_blocks) != 1:
        raise ConversationError(
            "malformed_artifact", "The managed conversation block must appear exactly once."
        )
    human_body = splice_managed_block(parsed.body, matches[0], "").strip("\n") + "\n"
    raw_turns = fm.get("turns", [])
    if not isinstance(raw_turns, list):
        raise ConversationError("invalid_turn", "Conversation turns must be a list.")
    turns = tuple(turn_from_dict(dict(item)) for item in raw_turns)
    try:
        metadata = ConversationMetadata(
            conversation_id=str(fm["conversation_id"]),
            title=str(fm["title"]),
            created_at=str(fm["created_at"]),
            updated_at=str(fm["updated_at"]),
            status=str(fm["status"]),  # type: ignore[arg-type]
            scope=scope_from_dict(
                fm.get("retrieval_scope") if isinstance(fm.get("retrieval_scope"), Mapping) else {}
            ),
            pinned_sources=tuple(str(item) for item in fm.get("pinned_sources", ())),
            excluded_sources=tuple(str(item) for item in fm.get("excluded_sources", ())),
            parent_conversation_id=str(fm["parent_conversation_id"])
            if fm.get("parent_conversation_id")
            else None,
            branch_from_turn_id=str(fm["branch_from_turn_id"])
            if fm.get("branch_from_turn_id")
            else None,
            schema_version=schema,
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ConversationError):
            raise
        raise ConversationError(
            "malformed_artifact", "Conversation metadata is malformed."
        ) from exc
    return ConversationArtifact(
        relative_path, f"sha256:{content_hash(content)}", metadata, turns, human_body
    )


class ConversationArtifactService:
    def __init__(self, *, vault_root: Path, runtime_dir: Path) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir

    def create(
        self,
        *,
        title: str,
        scope: RetrievalScope | None = None,
        now: datetime | None = None,
        parent_conversation_id: str | None = None,
        branch_from_turn_id: str | None = None,
        turns: tuple[ConversationTurn, ...] = (),
    ) -> ConversationArtifact:
        moment = _now(now)
        metadata = ConversationMetadata(
            _conversation_id(moment),
            title.strip(),
            moment.isoformat(),
            moment.isoformat(),
            "active",
            scope or RetrievalScope(),
            (),
            (),
            parent_conversation_id,
            branch_from_turn_id,
        )
        relative_path = _path(metadata)
        document = _document(metadata, turns, "## Annotations\n\n")
        _parse(self.vault_root / relative_path, relative_path, document)
        _atomic_write(self.vault_root, relative_path, document, expected_hash=None, create=True)
        return self.load(relative_path)

    def load(self, relative_path: str) -> ConversationArtifact:
        source = _read_source(self.vault_root, relative_path)
        return _parse(source.path, source.relative_path, source.content)

    def list(self, *, include_archived: bool = True) -> tuple[ConversationArtifact, ...]:
        try:
            sources = iter_vault_markdown(self.vault_root, roots=("conversations",))
        except VaultAccessError as exc:
            raise ConversationError(exc.code, str(exc)) from exc
        artifacts = tuple(_parse(item.path, item.relative_path, item.content) for item in sources)
        return tuple(
            sorted(
                (
                    item
                    for item in artifacts
                    if include_archived or item.metadata.status != "archived"
                ),
                key=lambda item: (item.metadata.updated_at, item.metadata.conversation_id),
                reverse=True,
            )
        )

    def find(self, conversation_id: str) -> ConversationArtifact:
        matches = [item for item in self.list() if item.metadata.conversation_id == conversation_id]
        if len(matches) != 1:
            raise ConversationError(
                "not_found" if not matches else "duplicate_identity",
                "Knowledge conversation could not be resolved uniquely.",
                {"conversation_id": conversation_id, "count": len(matches)},
            )
        return matches[0]

    def update(
        self,
        relative_path: str,
        *,
        expected_hash: str,
        title: str | None = None,
        status: str | None = None,
        scope: RetrievalScope | None = None,
        pinned_sources: tuple[str, ...] | None = None,
        excluded_sources: tuple[str, ...] | None = None,
        turns: tuple[ConversationTurn, ...] | None = None,
        now: datetime | None = None,
    ) -> ConversationArtifact:
        source = _read_source(self.vault_root, relative_path)
        current = _parse(source.path, source.relative_path, source.content)
        if current.content_hash != expected_hash:
            raise ConversationError("stale_artifact", "Conversation changed since it was loaded.")
        moment = _now(now)
        metadata = replace(
            current.metadata,
            title=(title.strip() if title is not None else current.metadata.title),
            status=(status if status is not None else current.metadata.status),  # type: ignore[arg-type]
            scope=scope or current.metadata.scope,
            pinned_sources=pinned_sources
            if pinned_sources is not None
            else current.metadata.pinned_sources,
            excluded_sources=excluded_sources
            if excluded_sources is not None
            else current.metadata.excluded_sources,
            updated_at=moment.isoformat(),
        )
        selected_turns = turns if turns is not None else current.turns
        parsed = parse_markdown_note(source.path, content=source.content)
        try:
            body = replace_managed_block(
                parsed.body, parsed.managed_blocks[0], _managed_body(selected_turns)
            )
        except ValueError as error:
            raise ConversationError("malformed_artifact", str(error)) from error
        dumped = yaml.safe_dump(
            metadata.to_frontmatter(selected_turns), sort_keys=False, allow_unicode=True
        ).rstrip()
        output = f"---\n{dumped}\n---\n{body}"
        _parse(self.vault_root / relative_path, relative_path, output)
        _atomic_write(
            self.vault_root,
            relative_path,
            output,
            expected_hash=expected_hash.removeprefix("sha256:"),
            create=False,
        )
        return self.load(relative_path)

    def append_turn(
        self,
        relative_path: str,
        turn: ConversationTurn,
        *,
        expected_hash: str,
        now: datetime | None = None,
    ) -> ConversationArtifact:
        current = self.load(relative_path)
        if any(item.turn_id == turn.turn_id for item in current.turns):
            raise ConversationError("duplicate_turn", "Conversation turn ID already exists.")
        return self.update(
            relative_path, expected_hash=expected_hash, turns=(*current.turns, turn), now=now
        )

    def rename(
        self, relative_path: str, title: str, *, expected_hash: str, now: datetime | None = None
    ) -> ConversationArtifact:
        return self.update(relative_path, expected_hash=expected_hash, title=title, now=now)

    def archive(
        self, relative_path: str, *, expected_hash: str, now: datetime | None = None
    ) -> ConversationArtifact:
        return self.update(relative_path, expected_hash=expected_hash, status="archived", now=now)

    def branch(
        self,
        relative_path: str,
        *,
        from_turn_id: str,
        title: str | None = None,
        now: datetime | None = None,
    ) -> ConversationArtifact:
        current = self.load(relative_path)
        index = next(
            (i for i, turn in enumerate(current.turns) if turn.turn_id == from_turn_id), None
        )
        if index is None:
            raise ConversationError("turn_not_found", "Branch source turn was not found.")
        return self.create(
            title=title or f"{current.metadata.title} branch",
            scope=current.metadata.scope,
            now=now,
            parent_conversation_id=current.metadata.conversation_id,
            branch_from_turn_id=from_turn_id,
            turns=current.turns[: index + 1],
        )
