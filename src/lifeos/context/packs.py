"""Inspectable context-pack assembly."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from lifeos.context.instructions import ContextInstruction, load_instruction_report
from lifeos.context.search import (
    ContextSearchError,
    PathFilter,
    SearchResult,
    focused_search_results,
    lexical_search_report,
)
from lifeos.diagnostics import DomainDiagnostic

if TYPE_CHECKING:
    from lifeos.retrieval.contracts import EmbeddingProvider, RetrievalScope, RerankingProvider
    from lifeos.retrieval.search import RetrievalEvidence, RetrievalResponse


@dataclass(frozen=True, slots=True)
class ContextSource(SearchResult):
    """A context source plus bounded, machine-readable retrieval provenance."""

    retrieval_mode: str = "lexical"
    retrieval_reasons: tuple[str, ...] = ()
    ranking: tuple[tuple[str, float], ...] = ()
    duplicate_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextPack:
    question: str
    instructions: tuple[ContextInstruction, ...]
    sources: tuple[ContextSource, ...]
    evidence_gaps: tuple[str, ...]
    omissions: tuple[str, ...]
    diagnostics: tuple[DomainDiagnostic, ...]


def _diagnostic_key(item: DomainDiagnostic) -> tuple[str, int, str, str, str]:
    return (item.source_path, item.line, item.code, item.severity, item.message)


def _as_context_source(
    item: SearchResult,
    *,
    retrieval_mode: str,
    retrieval_reasons: tuple[str, ...] = (),
) -> ContextSource:
    return ContextSource(
        path=item.path,
        title=item.title,
        description=item.description,
        excerpt=item.excerpt,
        score=item.score,
        matched_terms=item.matched_terms,
        score_evidence=item.score_evidence,
        retrieval_mode=retrieval_mode,
        retrieval_reasons=retrieval_reasons,
    )


def _bounded_excerpt(
    text: str,
    *,
    terms: tuple[str, ...] = (),
    width: int = 260,
) -> str:
    """Return a bounded excerpt centered on visible matching evidence when possible."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= width:
        return collapsed
    folded = collapsed.casefold()
    offsets = [folded.find(term.casefold()) for term in terms if term]
    offset = min((value for value in offsets if value >= 0), default=0)
    start = max(0, offset - width // 3)
    end = min(len(collapsed), start + width)
    snippet = collapsed[start:end].strip()
    if start:
        snippet = "…" + snippet
    if end < len(collapsed):
        snippet += "…"
    return snippet


def _retrieval_filter(
    *,
    vault_root: Path,
    scope: RetrievalScope,
    retrieval_mode: str,
    path_filter: PathFilter | None,
) -> PathFilter:
    """Compose caller narrowing with the authoritative retrieval privacy policy."""
    from lifeos.retrieval import RetrievalError, scope_decision
    from lifeos.retrieval.policy import load_retrieval_policy

    try:
        policy = load_retrieval_policy(vault_root)
    except RetrievalError as exc:
        raise ContextSearchError("Retrieval policy is invalid") from exc

    def allowed(path: str) -> bool:
        if path_filter is not None and not path_filter(path):
            return False
        try:
            return scope_decision(
                path,
                scope=scope,
                policy=policy,
                mode=cast(Literal["local", "external"], retrieval_mode),
            ).allowed
        except RetrievalError:
            return False

    return allowed


def _hybrid_context_source(
    *,
    item: RetrievalEvidence,
    lexical: SearchResult | None,
) -> ContextSource:
    ranking = item.ranking.to_dict()
    reasons = tuple(
        key
        for key in ("exact", "lexical", "semantic", "metadata", "link", "graph", "rerank")
        if float(ranking.get(key, 0.0)) > 0.0
    )
    matched = tuple(
        dict.fromkeys((*item.matched_terms, *(lexical.matched_terms if lexical is not None else ())))
    )
    excerpt = (
        lexical.excerpt
        if lexical is not None and lexical.excerpt
        else _bounded_excerpt(item.context_text, terms=matched)
    )
    return ContextSource(
        path=item.path,
        title=lexical.title if lexical is not None else item.title,
        description=lexical.description if lexical is not None else "",
        excerpt=excerpt,
        score=max(0, int(round(item.ranking.total * 1000))),
        matched_terms=matched,
        score_evidence=lexical.score_evidence if lexical is not None else (),
        retrieval_mode="hybrid",
        retrieval_reasons=reasons or ("hybrid-ranking",),
        ranking=tuple((key, float(value)) for key, value in ranking.items()),
        duplicate_paths=item.duplicate_paths,
    )


def _hybrid_sources(
    *,
    vault_root: Path,
    runtime_dir: Path,
    question: str,
    source_slots: int,
    focus_paths: tuple[str, ...],
    caller_path_filter: PathFilter | None,
    retrieval_scope: RetrievalScope,
    embedding_provider: EmbeddingProvider | None,
    reranker: RerankingProvider | None,
    graph_hints: Mapping[str, float] | None,
    lexical_by_path: Mapping[str, SearchResult],
    diagnostic_paths: frozenset[str],
) -> tuple[tuple[ContextSource, ...] | None, RetrievalResponse | None, str | None]:
    """Collect note-distinct hybrid sources without weakening pre-candidate privacy."""
    from lifeos.retrieval import HybridRetriever, RetrievalError, RetrievalRequest

    if source_slots <= 0:
        return (), None, None
    if caller_path_filter is not None:
        # An arbitrary callable cannot be translated into RetrievalScope and therefore cannot be
        # proven before hybrid ranking/provider disclosure. The lexical path applies it during
        # traversal before content access.
        return (
            None,
            None,
            "Hybrid retrieval was disabled for caller-scoped path filtering; used deterministic "
            "lexical fallback.",
        )
    if retrieval_scope.allow_protected:
        # The derived index is built from default-deny sources, so an explicitly broadened
        # protected request must use canonical policy-filtered lexical traversal rather than a
        # healthy index that cannot contain the authorized protected notes.
        return (
            None,
            None,
            "Hybrid retrieval was disabled for explicit protected scope; used deterministic "
            "lexical fallback.",
        )

    pinned = tuple(dict.fromkeys((*retrieval_scope.pinned_paths, *focus_paths)))
    base_scope = replace(retrieval_scope, pinned_paths=pinned)
    desired = source_slots + 1
    selected: list[ContextSource] = []
    seen: set[str] = set()
    response_for_state: RetrievalResponse | None = None
    last_result_paths: tuple[str, ...] = ()

    # Hybrid retrieval ranks chunks. Context Packs rank notes, so if one long note consumes the
    # first chunk window we retry with already represented paths excluded until enough distinct
    # note paths are available or retrieval is exhausted. Most queries complete in one pass.
    for _attempt in range(min(desired + 1, 22)):
        excluded = tuple(
            dict.fromkeys((*base_scope.excluded_paths, *focus_paths, *sorted(seen)))
        )
        scope = replace(base_scope, excluded_paths=excluded)
        candidate_limit = min(100, max(16, desired * 4))
        try:
            response = HybridRetriever(
                vault_root=vault_root,
                runtime_dir=runtime_dir,
            ).search(
                RetrievalRequest(
                    question,
                    scope=scope,
                    limit=candidate_limit,
                    context_budget=max(12_000, candidate_limit * 300),
                ),
                embedding_provider=embedding_provider,
                reranker=reranker,
                graph_hints=graph_hints,
            )
        except RetrievalError as exc:
            if exc.code == "cancelled":
                raise ContextSearchError("Hybrid retrieval was cancelled") from exc
            return (
                None,
                response_for_state,
                f"Hybrid retrieval was unavailable ({exc.code}); used deterministic lexical fallback.",
            )

        if response_for_state is None:
            response_for_state = response
        if response.index_state != "healthy":
            return (
                None,
                response,
                f"Hybrid retrieval index was {response.index_state}; used deterministic lexical fallback.",
            )

        current_paths = tuple(item.path for item in response.results)
        if not current_paths or current_paths == last_result_paths:
            break
        last_result_paths = current_paths
        added = False
        for item in response.results:
            if item.path in focus_paths or item.path in seen:
                continue
            seen.add(item.path)
            added = True
            if item.path in diagnostic_paths:
                continue
            selected.append(
                _hybrid_context_source(
                    item=item,
                    lexical=lexical_by_path.get(item.path),
                )
            )
            if len(selected) >= desired:
                return tuple(selected), response_for_state, None
        if not added:
            break

    return tuple(selected), response_for_state, None


def _merge_hybrid_and_lexical(
    *,
    hybrid: tuple[ContextSource, ...],
    lexical: tuple[SearchResult, ...],
    focused_paths: frozenset[str],
) -> tuple[ContextSource, ...]:
    """Keep authoritative hybrid order, then preserve lexical-only routing candidates."""
    merged = list(hybrid)
    seen = {item.path for item in hybrid} | set(focused_paths)
    for item in lexical:
        if item.path in seen:
            continue
        merged.append(
            _as_context_source(
                item,
                retrieval_mode="lexical",
                retrieval_reasons=("deterministic-lexical", "hybrid-augmentation"),
            )
        )
        seen.add(item.path)
    return tuple(merged)


def build_context_pack(
    *,
    vault_root: Path,
    question: str,
    limit: int = 8,
    focus_paths: tuple[str, ...] = (),
    path_filter: PathFilter | None = None,
    runtime_dir: Path | None = None,
    retrieval_scope: RetrievalScope | None = None,
    retrieval_mode: str = "local",
    embedding_provider: EmbeddingProvider | None = None,
    reranker: RerankingProvider | None = None,
    graph_hints: Mapping[str, float] | None = None,
) -> ContextPack:
    from lifeos.retrieval import RetrievalScope

    if type(limit) is not int or limit <= 0:
        raise ContextSearchError("limit must be a positive integer")
    if retrieval_mode not in {"local", "external"}:
        raise ContextSearchError("retrieval_mode must be local or external")

    scope = retrieval_scope or RetrievalScope()
    candidate_filter = _retrieval_filter(
        vault_root=vault_root,
        scope=scope,
        retrieval_mode=retrieval_mode,
        path_filter=path_filter,
    )
    # Instruction authority is separate from candidate scope narrowing. Only retrieval policy
    # and disclosure mode constrain discovery of the allowlisted instruction file; applicability
    # is then evaluated against the final selected sources.
    instruction_filter = _retrieval_filter(
        vault_root=vault_root,
        scope=RetrievalScope(allow_protected=scope.allow_protected),
        retrieval_mode=retrieval_mode,
        path_filter=None,
    )
    focused_results = focused_search_results(
        vault_root=vault_root,
        paths=focus_paths,
        path_filter=candidate_filter,
    )
    if len(focused_results) > limit:
        raise ContextSearchError("focus_paths cannot exceed the context source limit")
    focused = tuple(
        _as_context_source(
            item,
            retrieval_mode="focus",
            retrieval_reasons=("explicit-focus",),
        )
        for item in focused_results
    )

    remaining = max(0, limit - len(focused))
    search_diagnostics: tuple[DomainDiagnostic, ...] = ()
    hybrid: tuple[ContextSource, ...] | None = () if remaining == 0 else None
    hybrid_response: RetrievalResponse | None = None
    retrieval_omission: str | None = None
    lexical_results: tuple[SearchResult, ...] = ()

    if remaining > 0:
        search_report = lexical_search_report(
            vault_root=vault_root,
            query=question,
            limit=limit + len(focused) + 1,
            path_filter=candidate_filter,
        )
        search_diagnostics = search_report.diagnostics
        lexical_results = search_report.results
        lexical_by_path = {item.path: item for item in lexical_results}
        diagnostic_paths = frozenset(item.source_path for item in search_diagnostics)
        hybrid, hybrid_response, retrieval_omission = _hybrid_sources(
            vault_root=vault_root,
            runtime_dir=runtime_dir or (vault_root / ".lifeos"),
            question=question,
            source_slots=remaining,
            focus_paths=focus_paths,
            caller_path_filter=path_filter,
            retrieval_scope=scope,
            embedding_provider=embedding_provider,
            reranker=reranker,
            graph_hints=graph_hints,
            lexical_by_path=lexical_by_path,
            diagnostic_paths=diagnostic_paths,
        )

    focused_paths_set = frozenset(item.path for item in focused)
    if hybrid is None:
        candidates = tuple(
            _as_context_source(
                item,
                retrieval_mode="lexical-fallback",
                retrieval_reasons=("deterministic-lexical",),
            )
            for item in lexical_results
            if item.path not in focused_paths_set
        )
    else:
        candidates = _merge_hybrid_and_lexical(
            hybrid=hybrid,
            lexical=lexical_results,
            focused_paths=focused_paths_set,
        )

    limited = len(candidates) > remaining
    sources = (*focused, *candidates[:remaining])
    instruction_report = load_instruction_report(
        vault_root=vault_root,
        question=question,
        sources=sources,
        path_filter=instruction_filter,
    )
    gaps: list[str] = []
    omissions: list[str] = []

    if not sources:
        gaps.append("No matching canonical Markdown sources were found.")
    else:
        roots = {source.path.split("/", 1)[0] for source in sources}
        if len(sources) == 1:
            gaps.append("Only one matching source was found.")
        if len(roots) == 1:
            gaps.append("Matching evidence comes from a single vault area.")
        if all(not source.description for source in sources):
            gaps.append("Matching sources do not provide routing descriptions.")
        if limited:
            omissions.append(f"Results were limited to the top {limit} sources.")

    # Preserve the original omission ordering for compatibility, then append new retrieval
    # capability/policy disclosures.
    if not instruction_report.allowlisted_source_present:
        omissions.append("No system/instructions.yml file was present.")
    elif not instruction_report.instructions:
        omissions.append("No validated instructions applied to this context pack.")

    if not scope.allow_protected:
        omissions.append("Protected scopes were excluded from candidate selection by retrieval policy.")
    if retrieval_omission is not None:
        omissions.append(retrieval_omission)
    if hybrid_response is not None and hybrid is not None:
        if hybrid_response.semantic_state == "not-configured":
            omissions.append(
                "Semantic retrieval was not configured; hybrid ranking used local signals."
            )
        elif hybrid_response.semantic_state not in {"available", "not-used"}:
            omissions.append(
                "Semantic retrieval was "
                f"{hybrid_response.semantic_state}; hybrid ranking continued with local signals."
            )
        if reranker is not None and hybrid_response.rerank_state not in {
            "available",
            "not-requested",
        }:
            omissions.append(
                "Reranking was "
                f"{hybrid_response.rerank_state}; hybrid ranking continued without reranking."
            )
        if not hybrid_response.provider_disclosure.allowed:
            omissions.append(
                "Provider disclosure was blocked by retrieval policy; local retrieval results were used."
            )

    diagnostics = tuple(
        sorted(
            set((*search_diagnostics, *instruction_report.diagnostics)),
            key=_diagnostic_key,
        )
    )
    return ContextPack(
        question=question.strip(),
        instructions=instruction_report.instructions,
        sources=sources,
        evidence_gaps=tuple(gaps),
        omissions=tuple(omissions),
        diagnostics=diagnostics,
    )


def serialize_context_pack(pack: ContextPack) -> str:
    return json.dumps(asdict(pack), sort_keys=True, ensure_ascii=False, indent=2)


def format_context_pack(pack: ContextPack) -> str:
    lines = [f"Question: {pack.question}", ""]
    lines.append("Instructions")
    if pack.instructions:
        for item in pack.instructions:
            lines.append(
                f"  - [{item.id}] {item.text} "
                f"(authority {item.authority}, scope {item.scope}, priority {item.priority})"
            )
            lines.append(f"    applicability: {', '.join(item.applicability)}")
            if item.applicable_sources:
                lines.append(f"    sources: {', '.join(item.applicable_sources)}")
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Sources")
    if not pack.sources:
        lines.append("  none")
    for source in pack.sources:
        lines.append(f"  {source.path} (score {source.score}, mode {source.retrieval_mode})")
        if source.retrieval_reasons:
            lines.append(f"    retrieval reasons: {', '.join(source.retrieval_reasons)}")
        if source.score_evidence:
            evidence = ", ".join(
                f"{item.term}:{item.field} {item.match_count}×{item.weight}={item.score}"
                for item in source.score_evidence
            )
            lines.append(f"    score evidence: {evidence}")
        if source.description:
            lines.append(f"    {source.description}")
        if source.excerpt:
            lines.append(f"    {source.excerpt}")

    lines.append("")
    lines.append("Diagnostics")
    if pack.diagnostics:
        lines.extend(
            f"  - [{item.code}] {item.source_path}:{item.line} {item.message}"
            for item in pack.diagnostics
        )
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Evidence gaps")
    lines.extend(f"  - {item}" for item in pack.evidence_gaps)
    if not pack.evidence_gaps:
        lines.append("  none identified")

    lines.append("")
    lines.append("Omissions")
    lines.extend(f"  - {item}" for item in pack.omissions)
    if not pack.omissions:
        lines.append("  none")
    return "\n".join(lines)
