"""Deterministic token-aware lexical search over canonical Markdown notes."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lifeos.diagnostics import DomainDiagnostic, DiagnosticError, diagnostics_from_findings
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, iter_vault_markdown

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_FIELD_WEIGHTS: dict[str, tuple[int, int]] = {
    "title": (8, 1),
    "description": (5, 1),
    "path": (3, 1),
    "body": (1, 5),
}
SearchField = Literal["title", "description", "path", "body"]


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
) -> SearchReport:
    """Search Markdown by exact tokens and report parser omissions deterministically."""
    if not isinstance(vault_root, Path):
        raise ContextSearchError("vault_root must be a Path")
    if not isinstance(query, str) or not query.strip():
        raise ContextSearchError("query must be a non-empty string")
    if type(limit) is not int or limit <= 0:
        raise ContextSearchError("limit must be a positive integer")

    terms = lexical_terms(query)
    if not terms:
        raise ContextSearchError("query must contain searchable terms")

    results: list[SearchResult] = []
    diagnostics: list[DomainDiagnostic] = []

    try:
        files = iter_vault_markdown(vault_root)
    except VaultAccessError as exc:
        raise ContextSearchError(str(exc)) from exc

    for source in files:
        path = source.path
        parsed = parse_markdown_note(path, content=source.content)
        source_diagnostics = diagnostics_from_findings(parsed.findings, vault_root=vault_root)
        if source_diagnostics:
            diagnostics.extend(source_diagnostics)
            continue

        relative = source.relative_path
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


def lexical_search(
    *,
    vault_root: Path,
    query: str,
    limit: int = 8,
) -> tuple[SearchResult, ...]:
    """Compatibility wrapper returning only successful search results."""
    return lexical_search_report(vault_root=vault_root, query=query, limit=limit).results
