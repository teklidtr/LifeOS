"""Explainable hybrid ranking over the disposable structural index."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from lifeos.context.search import lexical_terms, token_sequence
from lifeos.retrieval.contracts import (
    AnswerEvidence,
    CancellationToken,
    EmbeddingProvider,
    ProviderDisclosure,
    ProviderError,
    RetrievalError,
    RetrievalPolicy,
    RetrievalRequest,
    RerankCandidate,
    RerankingProvider,
    build_provider_disclosure,
    scope_decision,
)
from lifeos.retrieval.index import RetrievalIndex
from lifeos.retrieval.models import IndexedChunk, IndexedDocument
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.retrieval.service import IndexHealth, RetrievalIndexService


@dataclass(frozen=True, slots=True)
class RankingComponents:
    exact: float = 0.0
    lexical: float = 0.0
    semantic: float = 0.0
    metadata: float = 0.0
    link: float = 0.0
    graph: float = 0.0
    rerank: float = 0.0

    @property
    def total(self) -> float:
        base = (
            self.exact * 0.10
            + self.lexical * 0.38
            + self.semantic * 0.32
            + self.metadata * 0.08
            + self.link * 0.07
            + self.graph * 0.05
        )
        return base * 0.85 + self.rerank * 0.15 if self.rerank else base

    def to_dict(self) -> dict[str, float]:
        return {**asdict(self), "total": self.total}


@dataclass(frozen=True, slots=True)
class RetrievalEvidence:
    evidence_id: str
    chunk_id: str
    path: str
    title: str
    heading: str | None
    heading_path: tuple[str, ...]
    start_line: int
    end_line: int
    block_id: str | None
    text: str
    context_text: str
    context_truncated: bool
    source_hash: str
    chunk_hash: str
    note_type: str | None
    source: str | None
    note_date: str | None
    tags: tuple[str, ...]
    scope_reason: str
    matched_terms: tuple[str, ...]
    ranking: RankingComponents
    duplicate_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["ranking"] = self.ranking.to_dict()
        value["obsidian_target"] = f"{self.path}#{self.heading}" if self.heading else self.path
        return value

    def answer_evidence(self) -> AnswerEvidence:
        return AnswerEvidence(
            self.evidence_id,
            self.path,
            self.heading,
            self.context_text,
            self.source_hash,
            self.chunk_hash,
        )


@dataclass(frozen=True, slots=True)
class RetrievalResponse:
    query: str
    results: tuple[RetrievalEvidence, ...]
    state: str
    index_state: str
    semantic_state: str
    rerank_state: str
    context_characters: int
    scope: dict[str, object]
    diagnostics: tuple[str, ...]
    provider_disclosure: ProviderDisclosure

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "results": [item.to_dict() for item in self.results],
            "state": self.state,
            "index_state": self.index_state,
            "semantic_state": self.semantic_state,
            "rerank_state": self.rerank_state,
            "context_characters": self.context_characters,
            "scope": self.scope,
            "diagnostics": list(self.diagnostics),
            "provider_disclosure": self.provider_disclosure.to_dict(),
        }


class HybridRetriever:
    def __init__(
        self,
        *,
        vault_root: Path,
        runtime_dir: Path,
        policy: RetrievalPolicy | None = None,
    ) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.policy = policy or load_retrieval_policy(vault_root)
        self.index_service = RetrievalIndexService(
            vault_root=vault_root, runtime_dir=runtime_dir, policy=self.policy
        )

    def _index_health(
        self,
        *,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> IndexHealth:
        """Return the health snapshot that governs this query."""
        return self.index_service.health(embedding_provider=embedding_provider)

    def _authorize_candidates(
        self,
        candidates: list[tuple[IndexedChunk, IndexedDocument, RankingComponents, tuple[str, ...]]],
        request: RetrievalRequest,
    ) -> list[tuple[IndexedChunk, IndexedDocument, RankingComponents, tuple[str, ...]]]:
        """Apply final local authorization before candidate text can reach a provider."""
        del request
        return candidates

    def search(
        self,
        request: RetrievalRequest,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        reranker: RerankingProvider | None = None,
        graph_hints: Mapping[str, float] | None = None,
        cancellation: CancellationToken | None = None,
        distinct_paths: bool = False,
    ) -> RetrievalResponse:
        """Retrieve explainable evidence, optionally limiting only after note-path deduplication."""
        token = cancellation or CancellationToken()
        health = self._index_health(embedding_provider=embedding_provider)
        if not health.active_usable:
            disclosure = build_provider_disclosure(
                evidence=(), capabilities=None, scope=request.scope, policy=self.policy
            )
            return RetrievalResponse(
                request.query,
                (),
                "degraded",
                health.state,
                "unavailable",
                "not-requested",
                0,
                request.scope.to_dict(),
                health.diagnostics or ("Build or rebuild the retrieval index.",),
                disclosure,
            )
        index = RetrievalIndex(self.index_service.active_path, create=False)
        diagnostics: list[str] = list(health.diagnostics)
        try:
            documents = {item.path: item for item in index.documents()}
            chunks = [
                item
                for item in index.chunks()
                if self._in_scope(item, documents[item.path], request)
            ]
            if not chunks:
                disclosure = build_provider_disclosure(
                    evidence=(), capabilities=None, scope=request.scope, policy=self.policy
                )
                return RetrievalResponse(
                    request.query,
                    (),
                    "no-results",
                    health.state,
                    "not-used",
                    "not-requested",
                    0,
                    request.scope.to_dict(),
                    tuple(diagnostics),
                    disclosure,
                )
            terms = lexical_terms(request.query)
            query_text = request.query.casefold().strip()
            semantic_scores: dict[str, float] = {}
            semantic_state = "not-configured"
            if embedding_provider is not None:
                try:
                    token.checkpoint()
                    query_batch = embedding_provider.embed(
                        [request.query],
                        timeout_seconds=request.timeout_seconds,
                        cancellation=token,
                    )
                    if len(query_batch.vectors) != 1:
                        raise ProviderError(
                            "malformed_provider_output",
                            "Embedding provider must return exactly one query vector.",
                        )
                    query_vector = query_batch.vectors[0]
                    embeddings = {
                        item.chunk_id: item.vector
                        for item in index.embeddings(embedding_provider.capabilities)
                    }
                    semantic_scores = {
                        chunk.chunk_id: max(0.0, _cosine(query_vector, embeddings[chunk.chunk_id]))
                        for chunk in chunks
                        if chunk.chunk_id in embeddings
                    }
                    semantic_state = "available" if semantic_scores else "missing-embeddings"
                except ProviderError as exc:
                    semantic_state = exc.code
                    diagnostics.append(f"semantic:{exc.code}:{exc.message}")
                except RetrievalError as exc:
                    if exc.code == "cancelled":
                        raise
                    semantic_state = exc.code
                    diagnostics.append(f"semantic:{exc.code}:{exc.message}")

            selected = set(request.scope.paths) | set(request.scope.pinned_paths)
            link_scores = _link_scores(chunks, selected)
            graph = {
                path: max(0.0, min(1.0, float(score)))
                for path, score in (graph_hints or {}).items()
            }
            candidates: list[
                tuple[IndexedChunk, IndexedDocument, RankingComponents, tuple[str, ...]]
            ] = []
            for chunk in chunks:
                token.checkpoint()
                document = documents[chunk.path]
                exact, lexical, matched = _lexical_scores(
                    query_text, terms, chunk=chunk, document=document
                )
                metadata = _metadata_score(terms, chunk, document, request)
                components = RankingComponents(
                    exact=exact,
                    lexical=lexical,
                    semantic=semantic_scores.get(chunk.chunk_id, 0.0),
                    metadata=metadata,
                    link=link_scores.get(chunk.path, 0.0),
                    graph=graph.get(chunk.path, 0.0),
                )
                if components.total > 0:
                    candidates.append((chunk, document, components, matched))
            candidates.sort(
                key=lambda item: (
                    -item[2].total,
                    item[0].path,
                    item[0].heading or "",
                    item[0].start_line,
                    item[0].chunk_id,
                )
            )
            candidates = self._authorize_candidates(candidates, request)

            rerank_state = "not-requested"
            disclosure_capabilities = (
                embedding_provider.capabilities if embedding_provider else None
            )
            if reranker is not None and candidates:
                preliminary = candidates[
                    : min(len(candidates), max(request.limit * 4, request.limit))
                ]
                evidence = tuple(
                    AnswerEvidence(
                        chunk.chunk_id,
                        chunk.path,
                        chunk.heading,
                        chunk.text,
                        str(document.content_hash),
                        chunk.chunk_hash,
                    )
                    for chunk, document, _, _ in preliminary
                )
                rerank_disclosure = build_provider_disclosure(
                    evidence=evidence,
                    capabilities=reranker.capabilities,
                    scope=request.scope,
                    policy=self.policy,
                )
                if rerank_disclosure.allowed:
                    try:
                        reranked = reranker.rerank(
                            request.query,
                            [
                                RerankCandidate(chunk.chunk_id, chunk.text, components.total)
                                for chunk, _, components, _ in preliminary
                            ],
                            timeout_seconds=request.timeout_seconds,
                            cancellation=token,
                        )
                        by_id = {
                            item.evidence_id: max(0.0, min(1.0, item.score)) for item in reranked
                        }
                        candidates = [
                            (
                                chunk,
                                document,
                                RankingComponents(
                                    **{
                                        **asdict(components),
                                        "rerank": by_id.get(chunk.chunk_id, 0.0),
                                    }
                                ),
                                matched,
                            )
                            for chunk, document, components, matched in candidates
                        ]
                        candidates.sort(
                            key=lambda item: (
                                -item[2].total,
                                item[0].path,
                                item[0].heading or "",
                                item[0].start_line,
                                item[0].chunk_id,
                            )
                        )
                        rerank_state = "available"
                        disclosure_capabilities = reranker.capabilities
                    except (ProviderError, RetrievalError) as exc:
                        if isinstance(exc, RetrievalError) and exc.code == "cancelled":
                            raise
                        rerank_state = getattr(exc, "code", "provider-error")
                        diagnostics.append(f"rerank:{rerank_state}:{exc}")
                else:
                    rerank_state = rerank_disclosure.reason
                    diagnostics.append(f"rerank:{rerank_state}")

            deduped = _deduplicate(candidates)
            if distinct_paths:
                deduped = _deduplicate_paths(deduped)
            results: list[RetrievalEvidence] = []
            used = 0
            for chunk, document, components, matched, duplicate_paths in deduped:
                if len(results) >= request.limit:
                    break
                remaining = request.context_budget - used
                if remaining <= 0:
                    break
                context_text = chunk.text[:remaining]
                truncated = len(context_text) < len(chunk.text)
                decision = scope_decision(
                    chunk.path, scope=request.scope, policy=self.policy, mode="local"
                )
                results.append(
                    RetrievalEvidence(
                        evidence_id=chunk.chunk_id,
                        chunk_id=chunk.chunk_id,
                        path=chunk.path,
                        title=document.title,
                        heading=chunk.heading,
                        heading_path=chunk.heading_path,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        block_id=chunk.block_id,
                        text=chunk.text,
                        context_text=context_text,
                        context_truncated=truncated,
                        source_hash=document.content_hash,
                        chunk_hash=chunk.chunk_hash,
                        note_type=document.note_type,
                        source=document.source,
                        note_date=document.note_date,
                        tags=document.tags,
                        scope_reason=decision.reason,
                        matched_terms=matched,
                        ranking=components,
                        duplicate_paths=duplicate_paths,
                    )
                )
                used += len(context_text)
            answer_evidence = tuple(item.answer_evidence() for item in results)
            disclosure = build_provider_disclosure(
                evidence=answer_evidence,
                capabilities=disclosure_capabilities,
                scope=request.scope,
                policy=self.policy,
            )
            state = "ready" if results else "no-results"
            if health.state not in {"healthy"}:
                state = "degraded" if results else "no-results"
            return RetrievalResponse(
                request.query,
                tuple(results),
                state,
                health.state,
                semantic_state,
                rerank_state,
                used,
                request.scope.to_dict(),
                tuple(diagnostics),
                disclosure,
            )
        finally:
            index.close()

    def _in_scope(
        self, chunk: IndexedChunk, document: IndexedDocument, request: RetrievalRequest
    ) -> bool:
        decision = scope_decision(chunk.path, scope=request.scope, policy=self.policy, mode="local")
        if not decision.allowed:
            return False
        scope = request.scope
        if scope.note_types and (document.note_type or "") not in scope.note_types:
            return False
        if scope.tags and not set(scope.tags) <= set(document.tags):
            return False
        if scope.sources and (document.source or "") not in scope.sources:
            return False
        if scope.date_from and (document.note_date is None or document.note_date < scope.date_from):
            return False
        if scope.date_to and (document.note_date is None or document.note_date > scope.date_to):
            return False
        return True


def _lexical_scores(
    query: str,
    terms: tuple[str, ...],
    *,
    chunk: IndexedChunk,
    document: IndexedDocument,
) -> tuple[float, float, tuple[str, ...]]:
    text = f"{document.title}\n{chunk.heading or ''}\n{chunk.text}".casefold()
    exact = 1.0 if query and query in text else 0.0
    tokens = token_sequence(text)
    counts = Counter(tokens)
    matched = tuple(term for term in terms if counts.get(term, 0))
    if not terms:
        return exact, 0.0, matched
    term_stems = tuple(_lexical_stem(term) for term in terms)
    text_stems = Counter(_lexical_stem(token) for token in tokens)
    stem_matched = tuple(
        term for term, stem in zip(terms, term_stems, strict=True) if text_stems.get(stem, 0)
    )
    coverage = len(matched) / len(terms)
    stem_coverage = len(stem_matched) / len(terms)
    frequency = sum(min(counts.get(term, 0), 4) for term in terms) / (4 * len(terms))
    title_tokens = token_sequence(document.title + " " + (chunk.heading or ""))
    title_stems = {_lexical_stem(token) for token in title_tokens}
    title_coverage = len(set(term_stems) & title_stems) / len(terms)
    lexical = coverage * 0.50 + stem_coverage * 0.20 + frequency * 0.15 + title_coverage * 0.15
    return exact, min(1.0, lexical), tuple(dict.fromkeys((*matched, *stem_matched)))


def _metadata_score(
    terms: tuple[str, ...],
    chunk: IndexedChunk,
    document: IndexedDocument,
    request: RetrievalRequest,
) -> float:
    score = 0.0
    if chunk.path in request.scope.pinned_paths:
        score += 1.0
    searchable = set(
        token_sequence(
            " ".join((*document.tags, document.note_type or "", document.source or "", chunk.path))
        )
    )
    if terms:
        score += len(set(terms) & searchable) / len(terms)
    return min(1.0, score)


def _link_scores(chunks: Sequence[IndexedChunk], selected: set[str]) -> dict[str, float]:
    if not selected:
        return {}
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    for chunk in chunks:
        for target, _ in chunk.links:
            outgoing[chunk.path].add(target)
            incoming[target].add(chunk.path)
    direct: set[str] = set()
    for path in selected:
        direct |= outgoing.get(path, set()) | incoming.get(path, set())
    second: set[str] = set()
    for path in direct:
        second |= outgoing.get(path, set()) | incoming.get(path, set())
    return {path: 1.0 for path in direct} | {path: 0.5 for path in second - direct - selected}


def _lexical_stem(token: str) -> str:
    """Return a small deterministic morphology key without language-model assumptions."""

    value = token.casefold()
    if value.endswith("ular") and len(value) > 6:
        value = value[:-4]
    elif value.endswith("tion") and len(value) > 6:
        value = value[:-4]
    elif value.endswith("ing") and len(value) > 6:
        value = value[:-3]
    elif value.endswith("ed") and len(value) > 5:
        value = value[:-2]
    elif value.endswith("es") and len(value) > 5:
        value = value[:-2]
    elif value.endswith("s") and len(value) > 4:
        value = value[:-1]
    if value.endswith("e") and len(value) > 5:
        value = value[:-1]
    return value


def _provenance_quality(document: IndexedDocument, chunk: IndexedChunk) -> tuple[int, ...]:
    """Prefer the richest canonical provenance when duplicate passages tie."""

    return (
        int(document.document_id.startswith("id:")),
        int(bool(document.note_type)),
        int(bool(document.source)),
        int(bool(document.note_date)),
        len(document.tags),
        len(chunk.links),
        int(bool(chunk.heading_path)),
    )


def _duplicate_signature(chunk: IndexedChunk) -> str:
    without_links = re.sub(r"\[\[[^\]]+\]\]", " ", chunk.text)
    without_links = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", without_links)
    normalized = " ".join(token_sequence(without_links))
    return normalized or chunk.normalized_hash


DedupedCandidate = tuple[
    IndexedChunk,
    IndexedDocument,
    RankingComponents,
    tuple[str, ...],
    tuple[str, ...],
]


def _deduplicate(
    candidates: Sequence[tuple[IndexedChunk, IndexedDocument, RankingComponents, tuple[str, ...]]],
) -> tuple[DedupedCandidate, ...]:
    groups: dict[
        str,
        list[tuple[IndexedChunk, IndexedDocument, RankingComponents, tuple[str, ...]]],
    ] = defaultdict(list)
    for item in candidates:
        groups[_duplicate_signature(item[0])].append(item)
    values: list[DedupedCandidate] = []
    for group in groups.values():
        representative = sorted(
            group,
            key=lambda item: (
                *(-value for value in _provenance_quality(item[1], item[0])),
                -item[2].total,
                item[0].path,
                item[0].start_line,
                item[0].chunk_id,
            ),
        )[0]
        scoring_leader = sorted(
            group,
            key=lambda item: (
                -item[2].total,
                item[0].path,
                item[0].start_line,
                item[0].chunk_id,
            ),
        )[0]
        matched = tuple(dict.fromkeys(term for item in group for term in item[3]))
        duplicates = tuple(
            sorted({item[0].path for item in group if item[0].path != representative[0].path})
        )
        values.append(
            (
                representative[0],
                representative[1],
                scoring_leader[2],
                matched,
                duplicates,
            )
        )
    values.sort(
        key=lambda item: (
            -item[2].total,
            item[0].path,
            item[0].heading or "",
            item[0].start_line,
            item[0].chunk_id,
        )
    )
    return tuple(values)


def _deduplicate_paths(candidates: Sequence[DedupedCandidate]) -> tuple[DedupedCandidate, ...]:
    """Keep the highest-ranked evidence chunk for each canonical note path."""
    seen: set[str] = set()
    values: list[DedupedCandidate] = []
    for item in candidates:
        path = item[0].path
        if path in seen:
            continue
        seen.add(path)
        values.append(item)
    return tuple(values)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
