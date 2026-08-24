"""Deterministic token-aware lexical search over canonical Markdown notes."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lifeos.diagnostics import DomainDiagnostic, DiagnosticError, diagnostics_from_findings
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, VaultMarkdownFile, iter_vault_markdown, read_vault_markdown
from lifeos.vault_paths import iter_vault_markdown_paths

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_FIELD_WEIGHTS: dict[str, tuple[int, int]] = {
    "title": (8, 1),
    "description": (5, 1),
    "path": (3, 1),
    "body": (1, 5),
}
SearchField = Literal["title", "description", "path", "body"]
PathFilter = Callable[[str], bool]


class ContextSearchError(DiagnosticError):
    """Raised when a context search request is invalid."""


@dataclass(frozen=True, slots=True)
class ScoreEvidence:
    """One independently reproducible contribution to a lexical score."""

    term: str
    field: SearchField
    match_count: int
    weight: int
    score: int


@dataclass(frozen=True, slots=True)
class SearchResult:
    path: str
    title: str
    description: str
    excerpt: str
    score: int
    matched_terms: tuple[str, ...]
    score_evidence: tuple[ScoreEvidence, ...]


@dataclass(frozen=True, slots=True)
class SearchReport:
    results: tuple[SearchResult, ...]
    diagnostics: tuple[DomainDiagnostic, ...]


def token_sequence(text: str) -> tuple[str, ...]:
    """Return Unicode-aware lexical tokens in source order, including repeats."""
    if not isinstance(text, str):
        return ()
    return tuple(match.group(0).casefold() for match in _TOKEN_RE.finditer(text))


def lexical_terms(text: str) -> tuple[str, ...]:
    """Return unique lexical tokens in deterministic first-seen order."""
    return tuple(dict.fromkeys(token_sequence(text)))


def _excerpt(body: str, terms: tuple[str, ...], *, width: int = 260) -> str:
    collapsed = " ".join(body.split())
    if not collapsed:
        return ""
    term_set = frozenset(terms)
    offset = next(
        (
            match.start()
            for match in _TOKEN_RE.finditer(collapsed)
            if match.group(0).casefold() in term_set
        ),
        0,
    )
    start = max(0, offset - width // 3)
    end = min(len(collapsed), start + width)
    snippet = collapsed[start:end].strip()
    if start:
        snippet = "…" + snippet
    if end < len(collapsed):
        snippet += "…"
    return snippet


def _field_evidence(
    *,
    terms: tuple[str, ...],
    field: SearchField,
    text: str,
) -> tuple[ScoreEvidence, ...]:
    weight, maximum = _FIELD_WEIGHTS[field]
    counts = Counter(token_sequence(text))
    evidence: list[ScoreEvidence] = []
    for term in terms:
        counted = min(counts.get(term, 0), maximum)
        if counted:
            evidence.append(
                ScoreEvidence(
                    term=term,
                    field=field,
                    match_count=counted,
                    weight=weight,
                    score=counted * weight,
                )
            )
    return tuple(evidence)


def lexical_search_report(
    *,
    vault_root: Path,
    query: str,
    limit: int = 8,
    path_prefix: str | None = None,
    path_filter: PathFilter | None = None,
) -> SearchReport:
    """Search Markdown by exact tokens and report parser omissions deterministically."""
    if not isinstance(vault_root, Path):
        raise ContextSearchError("vault_root must be a Path")
    if not isinstance(query, str) or not query.strip():
        raise ContextSearchError("query must be a non-empty string")
    if type(limit) is not int or limit <= 0:
        raise ContextSearchError("limit must be a positive integer")
    if path_prefix is not None:
        if not isinstance(path_prefix, str) or not path_prefix:
            raise ContextSearchError("path_prefix must be a non-empty string or None")
        if path_prefix.startswith("/") or ".." in Path(path_prefix).parts:
            raise ContextSearchError("path_prefix must be vault-relative")
        normalized_prefix = path_prefix.rstrip("/") + "/"
    else:
        normalized_prefix = None
    if path_filter is not None and not callable(path_filter):
        raise ContextSearchError("path_filter must be callable or None")

    terms = lexical_terms(query)
    if not terms:
        raise ContextSearchError("query must contain searchable terms")

    results: list[SearchResult] = []
    diagnostics: list[DomainDiagnostic] = []

    try:
        files = _search_sources(
            vault_root=vault_root,
            normalized_prefix=normalized_prefix,
            path_filter=path_filter,
        )
    except VaultAccessError as exc:
        raise ContextSearchError(str(exc)) from exc

    for source in files:
        relative = source.relative_path
        path = source.path
        parsed = parse_markdown_note(path, content=source.content)
        source_diagnostics = diagnostics_from_findings(parsed.findings, vault_root=vault_root)
        if source_diagnostics:
            diagnostics.extend(source_diagnostics)
            continue

        title = parsed.durable_fields.title or path.stem.replace("-", " ")
        description = parsed.durable_fields.description or ""
        body = parsed.body

        evidence = (
            *_field_evidence(terms=terms, field="title", text=title),
            *_field_evidence(terms=terms, field="description", text=description),
            *_field_evidence(terms=terms, field="path", text=relative),
            *_field_evidence(terms=terms, field="body", text=body),
        )
        if not evidence:
            continue
        matched = tuple(term for term in terms if any(item.term == term for item in evidence))
        score = sum(item.score for item in evidence)
        results.append(
            SearchResult(
                path=relative,
                title=title,
                description=description,
                excerpt=_excerpt(body, matched),
                score=score,
                matched_terms=matched,
                score_evidence=evidence,
            )
        )

    results.sort(key=lambda item: (-item.score, item.path))
    deduped_diagnostics = tuple(
        sorted(
            set(diagnostics),
            key=lambda item: (
                item.source_path,
                item.line,
                item.code,
                item.severity,
                item.message,
            ),
        )
    )
    return SearchReport(tuple(results[:limit]), deduped_diagnostics)


def _search_sources(
    *,
    vault_root: Path,
    normalized_prefix: str | None,
    path_filter: PathFilter | None,
) -> tuple[VaultMarkdownFile, ...]:
    if normalized_prefix is None and path_filter is None:
        return iter_vault_markdown(vault_root)

    prefix = normalized_prefix.rstrip("/") if normalized_prefix is not None else None

    def traversal_filter(path: str) -> bool:
        if path_filter is not None and not path_filter(path):
            return False
        if prefix is None:
            return True
        candidate = path.rstrip("/")
        return (
            candidate == prefix
            or candidate.startswith(prefix + "/")
            or prefix.startswith(candidate + "/")
        )

    paths = iter_vault_markdown_paths(vault_root, path_filter=traversal_filter)
    return tuple(read_vault_markdown(vault_root, relative) for relative in paths)


def focused_search_results(
    *,
    vault_root: Path,
    paths: tuple[str, ...],
    path_filter: PathFilter | None = None,
) -> tuple[SearchResult, ...]:
    """Load explicitly focused canonical Markdown as deterministic context sources."""
    if len(paths) > 8:
        raise ContextSearchError("focus_paths may contain at most 8 paths")
    if len(set(paths)) != len(paths):
        raise ContextSearchError("focus_paths must not contain duplicates")
    if path_filter is not None and not callable(path_filter):
        raise ContextSearchError("path_filter must be callable or None")

    results: list[SearchResult] = []
    for relative in paths:
        if not isinstance(relative, str) or not relative.strip():
            raise ContextSearchError("focus_paths must contain non-empty strings")
        if relative != relative.strip():
            raise ContextSearchError("focus_paths must not contain surrounding whitespace")
        if path_filter is not None and not path_filter(relative):
            raise ContextSearchError(f"Focus path is not available for retrieval: {relative}")
        try:
            source = read_vault_markdown(vault_root, relative)
        except VaultAccessError as exc:
            raise ContextSearchError(f"Invalid focus path {relative}: {exc}") from exc
        parsed = parse_markdown_note(source.path, content=source.content)
        diagnostics = diagnostics_from_findings(parsed.findings, vault_root=vault_root)
        if diagnostics:
            raise ContextSearchError(
                f"Focused source {relative} has parse findings and cannot be used as context"
            )
        title = parsed.durable_fields.title or source.path.stem.replace("-", " ")
        description = parsed.durable_fields.description or ""
        body = " ".join(parsed.body.split())
        excerpt = body[:260] + ("…" if len(body) > 260 else "")
        results.append(
            SearchResult(
                path=relative,
                title=title,
                description=description,
                excerpt=excerpt,
                score=0,
                matched_terms=(),
                score_evidence=(),
            )
        )
    return tuple(results)


def lexical_search(
    *,
    vault_root: Path,
    query: str,
    limit: int = 8,
) -> tuple[SearchResult, ...]:
    """Compatibility wrapper returning only successful search results."""
    return lexical_search_report(vault_root=vault_root, query=query, limit=limit).results
