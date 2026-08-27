"""Inspectable context-pack assembly."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

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


def _bounded_excerpt(text: str, *, width: int = 260) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= width:
        return collapsed
    return collapsed[:width].rstrip() + "…"


def _hybrid_context_source(
    *,
    vault_root: Path,
    item: RetrievalEvidence,
    path_filter: PathFilter | None,
) -> ContextSource:
    # Re-read the selected canonical note through the same focused-source path used by explicit
    # focus requests. This preserves the existing title/description contract and re-validates the
    # current path before the indexed evidence is exposed as Context Pack output.
    canonical = focused_search_results(
        vault_root=vault_root,
        paths=(item.path,),
        path_filter=path_filter,
    )[0]
    ranking = item.ranking.to_dict()
    reasons = tuple(
        key
        for key in ("exact", "lexical", "semantic", "metadata", "link", "graph", "rerank")
        if float(ranking.get(key, 0.0)) > 0.0
    )
    return ContextSource(
        path=item.path,
        title=canonical.title,
        description=canonical.description,
        excerpt=_bounded_excerpt(item.context_text),
        score=max(0, int(round(item.ranking.total * 1000))),
        matched_terms=item.matched_terms,
        score_evidence=(),
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
    limit: int,
    focus_paths: tuple[str, ...],
    path_filter: PathFilter | None,
    retrieval_scope: RetrievalScope | None,
    retrieval_mode: str,
    embedding_provider: EmbeddingProvider | None,
    reranker: RerankingProvider | None,
    graph_hints: Mapping[str, float] | None,
) -> tuple[tuple[ContextSource, ...] | None, RetrievalResponse | None, str | None]:
    from lifeos.retrieval import HybridRetriever, RetrievalError, RetrievalRequest, RetrievalScope

    scope = retrieval_scope or RetrievalScope()
    if retrieval_mode == "external" and scope.allow_protected:
        # HybridRetriever intentionally owns a local retrieval contract. Until its request model
        # carries external disclosure mode directly, do not admit explicitly requested protected
        # content into its candidate/provider path. Canonical lexical fallback can apply the
        # existing external policy before any protected content is read.
        return (
            None,
            None,
            "Hybrid retrieval was disabled for explicit protected external scope; used "
            "deterministic lexical fallback.",
        )

    pinned = tuple(dict.fromkeys((*scope.pinned_paths, *focus_paths)))
    scope = replace(scope, pinned_paths=pinned)
    candidate_limit = min(100, max(limit * 4, limit + len(focus_paths) + 1))
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
        return None, None, f"Hybrid retrieval was unavailable ({exc.code}); used deterministic lexical fallback."

    # A stale or otherwise unhealthy index is derived state. Do not let it displace canonical
    # lexical retrieval; use it only when the index is healthy and current.
    if response.index_state != "healthy":
        return (
            None,
            response,
            f"Hybrid retrieval index was {response.index_state}; used deterministic lexical fallback.",
        )

    focused = set(focus_paths)
    selected: list[ContextSource] = []
    seen: set[str] = set()
    for item in response.results:
        if item.path in focused or item.path in seen:
            continue
        if path_filter is not None and not path_filter(item.path):
            continue
        selected.append(
            _hybrid_context_source(vault_root=vault_root, item=item, path_filter=path_filter)
        )
        seen.add(item.path)
    return tuple(selected), response, None


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
    if type(limit) is not int or limit <= 0:
        raise ContextSearchError("limit must be a positive integer")
    if retrieval_mode not in {"local", "external"}:
        raise ContextSearchError("retrieval_mode must be local or external")
    focused_results = focused_search_results(
        vault_root=vault_root,
        paths=focus_paths,
        path_filter=path_filter,
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

    resolved_runtime_dir = runtime_dir or (vault_root / ".lifeos")
    hybrid, hybrid_response, retrieval_omission = _hybrid_sources(
        vault_root=vault_root,
        runtime_dir=resolved_runtime_dir,
        question=question,
        limit=limit,
        focus_paths=focus_paths,
        path_filter=path_filter,
        retrieval_scope=retrieval_scope,
        retrieval_mode=retrieval_mode,
        embedding_provider=embedding_provider,
        reranker=reranker,
        graph_hints=graph_hints,
    )

    search_diagnostics: tuple[DomainDiagnostic, ...] = ()
    remaining = max(0, limit - len(focused))
    if hybrid is None:
        search_report = lexical_search_report(
            vault_root=vault_root,
            query=question,
            limit=limit + len(focused) + 1,
            path_filter=path_filter,
        )
        search_diagnostics = search_report.diagnostics
        focused_paths_set = {item.path for item in focused}
        lexical = tuple(
            _as_context_source(
                item,
                retrieval_mode="lexical-fallback",
                retrieval_reasons=("deterministic-lexical",),
            )
            for item in search_report.results
            if item.path not in focused_paths_set
        )
        limited = len(lexical) > remaining
        candidates = lexical
    else:
        limited = len(hybrid) > remaining
        candidates = hybrid

    sources = (*focused, *candidates[:remaining])
    instruction_report = load_instruction_report(
        vault_root=vault_root,
        question=question,
        sources=sources,
        path_filter=path_filter,
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

    if retrieval_scope is not None and not retrieval_scope.allow_protected:
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
        if not hybrid_response.provider_disclosure.allowed:
            omissions.append(
                "Provider disclosure was blocked by retrieval policy; local retrieval results were used."
            )

    if not instruction_report.allowlisted_source_present:
        omissions.append("No system/instructions.yml file was present.")
    elif not instruction_report.instructions:
        omissions.append("No validated instructions applied to this context pack.")

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
