"""Bounded, policy-aware read primitives for agent-led vault exploration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from lifeos.context import (
    ContextSearchError,
    ContextSearchExecutionError,
    lexical_search_report,
)
from lifeos.diagnostics import DomainDiagnostic
from lifeos.facade.errors import ToolExecutionError, ToolNotFoundError, ToolValidationError
from lifeos.facade.models import ToolDescriptor, ToolEffect
from lifeos.markdown.parser import parse_markdown_note
from lifeos.retrieval import RetrievalError, RetrievalPolicy, RetrievalScope, scope_decision
from lifeos.retrieval.chunking import chunk_markdown_file
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.vault import VaultAccessError, is_markdown_path, read_vault_markdown
from lifeos.vault_paths import iter_vault_markdown_paths

RetrievalMode = Literal["local", "external"]
LinkKind = Literal["wikilink", "markdown"]
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|[^\]]+)?\]\]")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+?)(?:#([^)]*))?\)")
_MAX_TITLE_CHARACTERS = 512
_MAX_DESCRIPTION_CHARACTERS = 1_024
_MAX_LINK_DIAGNOSTICS = 100

VAULT_LIST_DESCRIPTOR = ToolDescriptor(
    name="vault.list",
    description="Discover bounded canonical Markdown paths and folders in the vault.",
    effect=ToolEffect.READ_ONLY,
)

VAULT_SEARCH_DESCRIPTOR = ToolDescriptor(
    name="vault.search",
    description="Search canonical Markdown across allowed vault scopes with lexical matching.",
    effect=ToolEffect.READ_ONLY,
)

VAULT_READ_MANY_DESCRIPTOR = ToolDescriptor(
    name="vault.read_many",
    description="Read a bounded set of canonical Markdown notes for comparison.",
    effect=ToolEffect.READ_ONLY,
)

VAULT_LINKS_DESCRIPTOR = ToolDescriptor(
    name="vault.links",
    description="Inspect outgoing references and backlinks between canonical Markdown notes.",
    effect=ToolEffect.READ_ONLY,
)


@dataclass(frozen=True, slots=True)
class VaultListRequest:
    prefix: str | None = None
    limit: int = 100
    allow_protected: bool = False
    after: str | None = None
    mode: RetrievalMode = "local"

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 200:
            raise ValueError("limit must be an integer between 1 and 200")
        if type(self.allow_protected) is not bool:
            raise ValueError("allow_protected must be a boolean")
        _validate_mode(self.mode)
        if self.prefix is not None:
            _validate_prefix(self.prefix)
        if self.after is not None:
            _validate_prefix(self.after)
            if self.prefix is not None and not _matches_prefix(self.after, self.prefix):
                raise ValueError("after must remain within prefix when prefix is provided")


@dataclass(frozen=True, slots=True)
class VaultPathEntry:
    path: str
    kind: Literal["file", "folder"]


@dataclass(frozen=True, slots=True)
class VaultListResult:
    prefix: str | None
    entries: tuple[VaultPathEntry, ...]
    truncated: bool
    next_after: str | None


@dataclass(frozen=True, slots=True)
class VaultSearchRequest:
    query: str
    prefix: str | None = None
    limit: int = 20
    allow_protected: bool = False
    mode: RetrievalMode = "local"

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query must be a non-empty string")
        if self.query != self.query.strip():
            raise ValueError("query must not contain surrounding whitespace")
        if type(self.limit) is not int or not 1 <= self.limit <= 50:
            raise ValueError("limit must be an integer between 1 and 50")
        if type(self.allow_protected) is not bool:
            raise ValueError("allow_protected must be a boolean")
        _validate_mode(self.mode)
        if self.prefix is not None:
            _validate_prefix(self.prefix)


@dataclass(frozen=True, slots=True)
class VaultSearchHit:
    path: str
    title: str
    description: str
    excerpt: str
    score: int
    matched_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VaultSearchResult:
    query: str
    hits: tuple[VaultSearchHit, ...]
    diagnostics: tuple[DomainDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class VaultReadManyRequest:
    paths: tuple[str, ...]
    max_characters: int = 40_000
    allow_protected: bool = False
    mode: RetrievalMode = "local"

    def __post_init__(self) -> None:
        if not 1 <= len(self.paths) <= 8:
            raise ValueError("paths must contain between 1 and 8 entries")
        if len(set(self.paths)) != len(self.paths):
            raise ValueError("paths must not contain duplicates")
        if type(self.max_characters) is not int or not 1 <= self.max_characters <= 100_000:
            raise ValueError("max_characters must be an integer between 1 and 100000")
        if type(self.allow_protected) is not bool:
            raise ValueError("allow_protected must be a boolean")
        _validate_mode(self.mode)
        for path in self.paths:
            _validate_markdown_path(path)


@dataclass(frozen=True, slots=True)
class VaultReadItem:
    path: str
    markdown_body: str
    title: str
    content_hash: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class VaultReadManyResult:
    items: tuple[VaultReadItem, ...]
    total_characters: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class VaultLinksRequest:
    path: str
    direction: Literal["outgoing", "backlinks", "both"] = "both"
    limit: int = 50
    allow_protected: bool = False
    offset: int = 0
    mode: RetrievalMode = "local"

    def __post_init__(self) -> None:
        _validate_markdown_path(self.path)
        if self.direction not in {"outgoing", "backlinks", "both"}:
            raise ValueError("direction must be outgoing, backlinks, or both")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        if type(self.allow_protected) is not bool:
            raise ValueError("allow_protected must be a boolean")
        if type(self.offset) is not int or self.offset < 0:
            raise ValueError("offset must be a non-negative integer")
        _validate_mode(self.mode)


@dataclass(frozen=True, slots=True)
class VaultLink:
    source_path: str
    target_path: str
    target_heading: str | None
    direction: Literal["outgoing", "backlink"]


@dataclass(frozen=True, slots=True)
class VaultLinksResult:
    path: str
    links: tuple[VaultLink, ...]
    truncated: bool
    next_offset: int | None
    diagnostics: tuple[DomainDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class _ParsedLink:
    kind: LinkKind
    target_path: str
    target_heading: str | None


def list_vault_paths(*, vault_root: Path, request: VaultListRequest) -> VaultListResult:
    """List allowed canonical Markdown files plus their folder paths deterministically."""
    policy = _policy(vault_root)
    scope = RetrievalScope(allow_protected=request.allow_protected)

    def traversal_filter(path: str) -> bool:
        return _allowed(
            path,
            scope=scope,
            policy=policy,
            mode=request.mode,
        ) and _matches_prefix_or_ancestor(path, request.prefix)

    try:
        allowed_files = list(
            iter_vault_markdown_paths(
                vault_root,
                path_filter=traversal_filter,
            )
        )
    except VaultAccessError as exc:
        raise ToolExecutionError(f"{exc.code}: {exc}") from exc

    folders: set[str] = set()
    for path in allowed_files:
        parent = PurePosixPath(path).parent
        while parent.as_posix() not in {".", ""}:
            folder = parent.as_posix()
            if _matches_prefix(folder, request.prefix):
                folders.add(folder)
            parent = parent.parent

    entries = [*(VaultPathEntry(path, "folder") for path in folders)]
    entries.extend(VaultPathEntry(path, "file") for path in allowed_files)
    entries.sort(key=lambda item: (item.path, item.kind))
    if request.after is not None:
        entries = [item for item in entries if item.path > request.after]
    truncated = len(entries) > request.limit
    page = tuple(entries[: request.limit])
    next_after = page[-1].path if truncated and page else None
    return VaultListResult(request.prefix, page, truncated, next_after)


def search_vault(*, vault_root: Path, request: VaultSearchRequest) -> VaultSearchResult:
    """Search allowed canonical Markdown without protected candidates crowding out results."""
    policy = _policy(vault_root)
    scope = RetrievalScope(allow_protected=request.allow_protected)
    try:
        report = lexical_search_report(
            vault_root=vault_root,
            query=request.query,
            limit=request.limit,
            path_prefix=request.prefix,
            path_filter=lambda path: _allowed(
                path,
                scope=scope,
                policy=policy,
                mode=request.mode,
            ),
        )
    except ContextSearchExecutionError as exc:
        raise ToolExecutionError(str(exc)) from exc
    except ContextSearchError as exc:
        raise ToolValidationError(str(exc)) from exc
    hits = tuple(
        VaultSearchHit(
            path=item.path,
            title=item.title[:_MAX_TITLE_CHARACTERS],
            description=item.description[:_MAX_DESCRIPTION_CHARACTERS],
            excerpt=item.excerpt,
            score=item.score,
            matched_terms=item.matched_terms,
        )
        for item in report.results
    )
    return VaultSearchResult(request.query, hits, report.diagnostics)


def read_many(*, vault_root: Path, request: VaultReadManyRequest) -> VaultReadManyResult:
    """Read up to eight allowed notes under one body budget and bounded metadata."""
    policy = _policy(vault_root)
    scope = RetrievalScope(allow_protected=request.allow_protected)
    remaining = request.max_characters
    items: list[VaultReadItem] = []
    any_truncated = False

    for path in request.paths:
        _require_allowed(path, scope=scope, policy=policy, mode=request.mode)
        try:
            source = read_vault_markdown(vault_root, path)
        except VaultAccessError as exc:
            if exc.code == "not-found":
                raise ToolNotFoundError("Target file not found") from exc
            if exc.code in {"unsafe-symlink", "invalid-path"}:
                raise ToolValidationError("Unsafe vault path") from exc
            raise ToolExecutionError("Failed to read file") from exc
        parsed = parse_markdown_note(source.path, content=source.content)
        body = parsed.body
        included = body[:remaining]
        body_truncated = len(included) < len(body)
        raw_title = parsed.durable_fields.title or source.path.stem.replace("-", " ")
        title = raw_title[:_MAX_TITLE_CHARACTERS]
        title_truncated = len(title) < len(raw_title)
        truncated = body_truncated or title_truncated
        any_truncated = any_truncated or truncated
        items.append(
            VaultReadItem(
                path=path,
                markdown_body=included,
                title=title,
                content_hash=_sha256_prefixed(source.content_bytes),
                truncated=truncated,
            )
        )
        remaining -= len(included)
        if remaining <= 0:
            any_truncated = any_truncated or len(items) < len(request.paths)
            break

    return VaultReadManyResult(
        items=tuple(items),
        total_characters=request.max_characters - remaining,
        truncated=any_truncated or len(items) < len(request.paths),
    )


def inspect_links(*, vault_root: Path, request: VaultLinksRequest) -> VaultLinksResult:
    """Resolve current canonical outgoing links/backlinks by deterministic Markdown parsing."""
    policy = _policy(vault_root)
    scope = RetrievalScope(allow_protected=request.allow_protected)
    _require_allowed(request.path, scope=scope, policy=policy, mode=request.mode)
    try:
        allowed_paths = set(
            iter_vault_markdown_paths(
                vault_root,
                path_filter=lambda path: _allowed(
                    path,
                    scope=scope,
                    policy=policy,
                    mode=request.mode,
                ),
            )
        )
    except VaultAccessError as exc:
        raise ToolExecutionError(f"{exc.code}: {exc}") from exc
    if request.path not in allowed_paths:
        raise ToolNotFoundError("Target file not found")

    basename_index: dict[str, list[str]] = {}
    for path in allowed_paths:
        basename_index.setdefault(PurePosixPath(path).name, []).append(path)

    links: set[VaultLink] = set()
    diagnostics: list[DomainDiagnostic] = []
    source_paths = (
        (request.path,) if request.direction == "outgoing" else tuple(sorted(allowed_paths))
    )
    for source_path in source_paths:
        try:
            source = read_vault_markdown(vault_root, source_path)
        except VaultAccessError as exc:
            if source_path == request.path:
                raise ToolExecutionError("Requested note could not be read") from exc
            diagnostics.append(
                DomainDiagnostic(
                    code="link-source-read-failed",
                    severity="warning",
                    source_path=source_path,
                    line=1,
                    message="Source was skipped because it could not be read for link discovery.",
                )
            )
            continue
        try:
            chunks = chunk_markdown_file(source).chunks
        except RetrievalError as exc:
            if source_path == request.path:
                raise ToolExecutionError("Requested note could not be parsed") from exc
            diagnostics.append(
                DomainDiagnostic(
                    code="link-source-parse-failed",
                    severity="warning",
                    source_path=source_path,
                    line=1,
                    message="Source was skipped because it could not be parsed for link discovery.",
                )
            )
            continue
        for chunk in chunks:
            for parsed_link in _typed_links(chunk.text):
                target_path = _resolve_typed_link(
                    parsed_link,
                    source_path=source_path,
                    allowed_paths=allowed_paths,
                    basename_index=basename_index,
                )
                if target_path is None:
                    continue
                if request.direction in {"outgoing", "both"} and source_path == request.path:
                    links.add(
                        VaultLink(
                            source_path=request.path,
                            target_path=target_path,
                            target_heading=parsed_link.target_heading,
                            direction="outgoing",
                        )
                    )
                if request.direction in {"backlinks", "both"} and target_path == request.path:
                    links.add(
                        VaultLink(
                            source_path=source_path,
                            target_path=request.path,
                            target_heading=parsed_link.target_heading,
                            direction="backlink",
                        )
                    )
    ordered = tuple(
        sorted(
            links,
            key=lambda item: (
                item.direction,
                item.source_path,
                item.target_path,
                item.target_heading or "",
            ),
        )
    )
    page = ordered[request.offset : request.offset + request.limit]
    consumed = request.offset + len(page)
    truncated = consumed < len(ordered)
    next_offset = consumed if truncated else None
    return VaultLinksResult(
        request.path,
        page,
        truncated,
        next_offset,
        _bounded_link_diagnostics(diagnostics, request_path=request.path),
    )


def _bounded_link_diagnostics(
    diagnostics: list[DomainDiagnostic],
    *,
    request_path: str,
) -> tuple[DomainDiagnostic, ...]:
    ordered = sorted(
        set(diagnostics),
        key=lambda item: (
            item.source_path,
            item.line,
            item.code,
            item.severity,
            item.message,
        ),
    )
    if len(ordered) <= _MAX_LINK_DIAGNOSTICS:
        return tuple(ordered)
    visible = ordered[: _MAX_LINK_DIAGNOSTICS - 1]
    visible.append(
        DomainDiagnostic(
            code="link-diagnostics-truncated",
            severity="warning",
            source_path=request_path,
            line=1,
            message=(
                f"{len(ordered) - len(visible)} additional link-source diagnostics were "
                "omitted by the output bound."
            ),
        )
    )
    return tuple(visible)


def _typed_links(text: str) -> tuple[_ParsedLink, ...]:
    results: set[_ParsedLink] = set()
    for target, heading in _WIKILINK_RE.findall(text):
        path = target.strip().strip("/")
        if not is_markdown_path(path):
            path += ".md"
        results.add(_ParsedLink("wikilink", path, heading.strip() or None))
    for target, heading in _MARKDOWN_LINK_RE.findall(text):
        if "://" in target or target.startswith("#"):
            continue
        path = target.split("?", 1)[0]
        if is_markdown_path(path):
            results.add(_ParsedLink("markdown", path, heading.strip() or None))
    return tuple(
        sorted(
            results,
            key=lambda item: (item.kind, item.target_path, item.target_heading or ""),
        )
    )


def _resolve_typed_link(
    link: _ParsedLink,
    *,
    source_path: str,
    allowed_paths: set[str],
    basename_index: dict[str, list[str]],
) -> str | None:
    if link.kind == "markdown":
        if link.target_path.startswith("/"):
            candidate = link.target_path.strip("/")
        else:
            candidate = _source_relative_target(link.target_path, source_path=source_path)
        return candidate if candidate in allowed_paths else None

    candidate = link.target_path.strip("/")
    if candidate in allowed_paths:
        return candidate
    if "/" in candidate:
        return None
    candidates = basename_index.get(PurePosixPath(candidate).name, [])
    if len(candidates) == 1:
        return candidates[0]
    return None


def _source_relative_target(target_path: str, *, source_path: str) -> str:
    parent = PurePosixPath(source_path).parent
    parts: list[str] = []
    for part in (parent / target_path).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part not in {"", "."}:
            parts.append(part)
    return PurePosixPath(*parts).as_posix()


def _policy(vault_root: Path) -> RetrievalPolicy:
    try:
        return load_retrieval_policy(vault_root)
    except RetrievalError as exc:
        raise ToolExecutionError("Retrieval policy is invalid") from exc


def _allowed(
    path: str,
    *,
    scope: RetrievalScope,
    policy: RetrievalPolicy,
    mode: RetrievalMode,
) -> bool:
    try:
        return scope_decision(path, scope=scope, policy=policy, mode=mode).allowed
    except RetrievalError:
        return False


def _require_allowed(
    path: str,
    *,
    scope: RetrievalScope,
    policy: RetrievalPolicy,
    mode: RetrievalMode,
) -> None:
    try:
        decision = scope_decision(path, scope=scope, policy=policy, mode=mode)
    except RetrievalError as exc:
        raise ToolValidationError("Invalid vault path") from exc
    if not decision.allowed:
        raise ToolValidationError(f"Vault path is not available for exploration: {decision.reason}")


def _validate_mode(mode: RetrievalMode) -> None:
    if mode not in {"local", "external"}:
        raise ValueError("mode must be local or external")


def _validate_prefix(prefix: str) -> None:
    if not isinstance(prefix, str) or not prefix.strip() or prefix != prefix.strip():
        raise ValueError("prefix must be a non-empty vault-relative path")
    if "\\" in prefix or "\x00" in prefix:
        raise ValueError("prefix must be a POSIX vault-relative path")
    pure = PurePosixPath(prefix.rstrip("/"))
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("prefix must stay within the vault")


def _validate_markdown_path(path: str) -> None:
    if not isinstance(path, str) or not path.strip() or path != path.strip():
        raise ValueError("paths must be non-empty vault-relative strings")
    if not is_markdown_path(path):
        raise ValueError("only Markdown paths are supported")
    _validate_prefix(path)


def _matches_prefix(path: str, prefix: str | None) -> bool:
    if prefix is None:
        return True
    normalized = prefix.rstrip("/")
    return path == normalized or path.startswith(normalized + "/")


def _matches_prefix_or_ancestor(path: str, prefix: str | None) -> bool:
    if prefix is None:
        return True
    normalized = prefix.rstrip("/")
    candidate = path.rstrip("/")
    return _matches_prefix(candidate, normalized) or normalized.startswith(candidate + "/")


def _sha256_prefixed(content: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(content).hexdigest()
