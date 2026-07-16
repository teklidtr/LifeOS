"""Deterministic heading-aware chunking for canonical Markdown notes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from lifeos.context.search import token_sequence
from lifeos.markdown.parser import FENCED_CODE_RE, parse_markdown_note
from lifeos.retrieval.contracts import RetrievalError
from lifeos.retrieval.models import ChunkedNote, IndexedChunk, IndexedDocument
from lifeos.vault import VaultMarkdownFile

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BLOCK_ID_RE = re.compile(r"(?:^|\s)\^([A-Za-z0-9][A-Za-z0-9_-]{0,63})\s*$")
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|[^\]]+)?\]\]")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+?)(?:#([^)]*))?\)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def chunk_markdown_file(
    source: VaultMarkdownFile,
    *,
    indexed_at: datetime | None = None,
    max_chunk_characters: int = 1_800,
) -> ChunkedNote:
    if not source.relative_path.endswith(".md"):
        raise RetrievalError("unsupported_file", "Only Markdown files can be indexed.")
    if max_chunk_characters < 256:
        raise RetrievalError("invalid_chunk_budget", "max_chunk_characters must be at least 256.")
    parsed = parse_markdown_note(source.path, content=source.content)
    errors = tuple(f"{item.code}@{item.line}: {item.message}" for item in parsed.findings if item.severity == "error")
    if errors:
        raise RetrievalError("malformed_note", "The note is structurally invalid.", {"path": source.relative_path, "diagnostics": errors})
    moment = indexed_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise RetrievalError("invalid_timestamp", "indexed_at must be timezone-aware.")

    frontmatter = _json_safe(dict(parsed.frontmatter))
    durable_id = parsed.durable_fields.id
    document_id = f"id:{durable_id}" if durable_id else f"path:{_digest(source.relative_path)}"
    title = parsed.durable_fields.title or source.path.stem.replace("-", " ")
    note_type = parsed.durable_fields.type
    tags = _tags(frontmatter.get("tags"))
    note_source = _optional_string(frontmatter.get("source"))
    note_date = _note_date(frontmatter)
    content_hash = _prefixed(source.content_bytes)
    document = IndexedDocument(
        document_id=document_id,
        path=source.relative_path,
        title=title,
        note_type=note_type,
        source=note_source,
        note_date=note_date,
        tags=tags,
        frontmatter=frontmatter,
        content_hash=content_hash,
        indexed_at=moment.astimezone(timezone.utc).isoformat(),
    )

    body_start = _body_start_line(source.content)
    sections = _sections(parsed.body, body_start_line=body_start)
    chunks: list[IndexedChunk] = []
    seen: set[tuple[str, str | None]] = set()
    diagnostics: list[str] = []
    structural_index = 0
    for heading_path, heading, start_line, lines in sections:
        for part_start, part_end, text in _bounded_structural_parts(lines, start_line=start_line, maximum=max_chunk_characters):
            normalized = _normalize_text(text)
            if not normalized:
                continue
            block_match = _BLOCK_ID_RE.search(text)
            block_id = block_match.group(1) if block_match else None
            dedupe_key = (_digest(normalized), block_id)
            if dedupe_key in seen:
                diagnostics.append(f"duplicate-passage:{source.relative_path}:{part_start}-{part_end}")
                continue
            seen.add(dedupe_key)
            structural_index += 1
            normalized_hash = _prefixed(normalized.encode("utf-8"))
            chunk_hash = _prefixed(text.encode("utf-8"))
            identity_payload = json.dumps(
                [document_id, list(heading_path), block_id, structural_index, normalized_hash],
                separators=(",", ":"),
                ensure_ascii=False,
            )
            chunk_id = f"chunk:{_digest(identity_payload)}"
            chunks.append(
                IndexedChunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    path=source.relative_path,
                    heading=heading,
                    heading_path=heading_path,
                    start_line=part_start,
                    end_line=part_end,
                    block_id=block_id,
                    text=text.strip(),
                    normalized_hash=normalized_hash,
                    chunk_hash=chunk_hash,
                    links=_links(text, source.relative_path),
                    token_count=len(token_sequence(text)),
                    metadata={
                        "title": title,
                        "note_type": note_type,
                        "source": note_source,
                        "date": note_date,
                        "tags": list(tags),
                        "content_hash": content_hash,
                    },
                )
            )
    return ChunkedNote(document, tuple(chunks), tuple(diagnostics))


def reidentify_note(note: ChunkedNote, document_id: str) -> ChunkedNote:
    """Preserve a prior document identity during an incremental rename."""
    if not document_id:
        raise RetrievalError("invalid_document_id", "document_id must be non-empty.")
    document = replace(note.document, document_id=document_id)
    chunks: list[IndexedChunk] = []
    for index, chunk in enumerate(note.chunks, start=1):
        payload = json.dumps(
            [document_id, list(chunk.heading_path), chunk.block_id, index, chunk.normalized_hash],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        chunks.append(replace(chunk, document_id=document_id, chunk_id=f"chunk:{_digest(payload)}"))
    return ChunkedNote(document, tuple(chunks), note.diagnostics)


def _sections(body: str, *, body_start_line: int) -> tuple[tuple[tuple[str, ...], str | None, int, tuple[str, ...]], ...]:
    lines = body.splitlines()
    sections: list[tuple[tuple[str, ...], str | None, int, tuple[str, ...]]] = []
    heading_stack: list[str] = []
    current_heading: str | None = None
    current_path: tuple[str, ...] = ()
    current_start = body_start_line
    current_lines: list[str] = []
    fence: tuple[str, int] | None = None

    def flush() -> None:
        nonlocal current_lines
        if any(line.strip() for line in current_lines):
            sections.append((current_path, current_heading, current_start, tuple(current_lines)))
        current_lines = []

    for offset, line in enumerate(lines):
        line_no = body_start_line + offset
        fence_match = FENCED_CODE_RE.match(line)
        if fence_match:
            marker = fence_match.group(2)
            char = marker[0]
            if fence is None:
                fence = (char, len(marker))
            elif fence[0] == char and len(marker) >= fence[1]:
                fence = None
            current_lines.append(line)
            continue
        match = _HEADING_RE.match(line) if fence is None else None
        if match:
            flush()
            level = len(match.group(1))
            heading = match.group(2).strip()
            heading_stack[:] = heading_stack[: level - 1]
            while len(heading_stack) < level - 1:
                heading_stack.append("")
            heading_stack.append(heading)
            current_heading = heading
            current_path = tuple(item for item in heading_stack if item)
            current_start = line_no + 1
            continue
        current_lines.append(line)
    flush()
    return tuple(sections)


def _bounded_structural_parts(
    lines: tuple[str, ...], *, start_line: int, maximum: int
) -> tuple[tuple[int, int, str], ...]:
    blocks: list[tuple[int, int, str]] = []
    buffer: list[str] = []
    block_start = start_line
    in_fence = False
    fence_char = ""
    fence_len = 0

    def flush(line_no: int) -> None:
        nonlocal buffer, block_start
        text = "\n".join(buffer).strip()
        if text:
            blocks.extend(_split_oversized(text, block_start, line_no, maximum))
        buffer = []
        block_start = line_no + 1

    for offset, line in enumerate(lines):
        line_no = start_line + offset
        match = FENCED_CODE_RE.match(line)
        if match:
            marker = match.group(2)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_len:
                in_fence = False
        if not buffer:
            block_start = line_no
        if not line.strip() and not in_fence:
            flush(line_no - 1)
        else:
            buffer.append(line)
    flush(start_line + len(lines) - 1)

    combined: list[tuple[int, int, str]] = []
    pending: list[tuple[int, int, str]] = []
    size = 0
    seen_blocks: set[str] = set()
    for block in blocks:
        has_block_id = _BLOCK_ID_RE.search(block[2]) is not None
        normalized_block = _normalize_text(block[2])
        repeated_block = normalized_block in seen_blocks
        seen_blocks.add(normalized_block)
        addition = len(block[2]) + (2 if pending else 0)
        if pending and (size + addition > maximum or has_block_id or repeated_block):
            combined.append((pending[0][0], pending[-1][1], "\n\n".join(item[2] for item in pending)))
            pending = []
            size = 0
        pending.append(block)
        size += len(block[2])
        if has_block_id or repeated_block:
            combined.append((block[0], block[1], block[2]))
            pending = []
            size = 0
    if pending:
        combined.append((pending[0][0], pending[-1][1], "\n\n".join(item[2] for item in pending)))
    return tuple(combined)


def _split_oversized(text: str, start: int, end: int, maximum: int) -> list[tuple[int, int, str]]:
    if len(text) <= maximum:
        return [(start, end, text)]
    sentences = _SENTENCE_SPLIT_RE.split(text)
    if len(sentences) == 1:
        lines = text.splitlines()
        if len(lines) > 1:
            sentences = lines
    parts: list[str] = []
    current = ""
    for unit in sentences:
        candidate = f"{current} {unit}".strip() if current else unit
        if current and len(candidate) > maximum:
            parts.append(current)
            current = unit
        elif len(unit) > maximum and not current:
            for offset in range(0, len(unit), maximum):
                parts.append(unit[offset : offset + maximum])
            current = ""
        else:
            current = candidate
    if current:
        parts.append(current)
    return [(start, end, part) for part in parts if part.strip()]


def _links(text: str, source_path: str) -> tuple[tuple[str, str | None], ...]:
    results: set[tuple[str, str | None]] = set()
    for target, heading in _WIKILINK_RE.findall(text):
        path = target.strip()
        if not path.endswith(".md"):
            path += ".md"
        results.add((_resolve_link(path, source_path), heading.strip() or None))
    for target, heading in _MARKDOWN_LINK_RE.findall(text):
        if "://" in target or target.startswith("#"):
            continue
        path = target.split("?", 1)[0]
        if path.endswith(".md"):
            results.add((_resolve_link(path, source_path), heading.strip() or None))
    return tuple(sorted(results))


def _resolve_link(target: str, source_path: str) -> str:
    if target.startswith("/") or ("/" in target and not target.startswith(("./", "../"))):
        return target.strip("/")
    parent = PurePosixPath(source_path).parent
    parts: list[str] = []
    for part in (parent / target).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part not in {"", "."}:
            parts.append(part)
    return PurePosixPath(*parts).as_posix()


def _body_start_line(content: str) -> int:
    lines = content.splitlines()
    if not lines or lines[0].lstrip("\ufeff") != "---":
        return 1
    for index, line in enumerate(lines[1:], start=2):
        if line == "---":
            return index + 1
    return 1


def _tags(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(dict.fromkeys(item.strip().lstrip("#") for item in value.split() if item.strip()))
    if isinstance(value, (list, tuple)):
        return tuple(dict.fromkeys(str(item).strip().lstrip("#") for item in value if str(item).strip()))
    return ()


def _note_date(frontmatter: dict[str, Any]) -> str | None:
    for key in ("date", "created", "created_at", "day", "period_start"):
        value = frontmatter.get(key)
        if value is not None:
            return str(value)[:10]
    return None


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _normalize_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _prefixed(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()
