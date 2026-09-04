"""Evidence-first grounded answer orchestration and stale-citation validation."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from lifeos.patterns.context import (
    PersonalPatternContext,
    PersonalPatternContextError,
    archived_personal_pattern_paths_for_scope,
    build_personal_pattern_context,
    render_personal_pattern_evidence,
)
from lifeos.retrieval import (
    AnswerProvider,
    CancellationToken,
    EmbeddingProvider,
    GeneratedAnswer,
    HybridRetriever,
    ProviderError,
    RetrievalEvidence,
    RetrievalPolicy,
    RetrievalRequest,
    RetrievalScope,
    build_provider_disclosure,
)
from lifeos.retrieval.chunking import chunk_markdown_file
from lifeos.vault import VaultAccessError, read_vault_markdown

from .artifact import ConversationArtifactService
from .contracts import (
    ConversationArtifact,
    ConversationError,
    ConversationEvidence,
    ConversationParagraph,
    ConversationTurn,
)


def _moment(value: datetime | None = None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ConversationError("invalid_timestamp", "Conversation timestamps must be timezone-aware.")
    return moment.astimezone(timezone.utc)


def _turn_id(artifact: ConversationArtifact) -> str:
    return f"turn-{len(artifact.turns) + 1:03d}"


def _pattern_annotated_results(
    results: Sequence[RetrievalEvidence], context: PersonalPatternContext
) -> tuple[RetrievalEvidence, ...]:
    by_path = {item.pattern_path: item for item in context.items}
    annotated: list[RetrievalEvidence] = []
    for result in results:
        pattern = by_path.get(result.path)
        if pattern is None:
            annotated.append(result)
            continue
        rendered = render_personal_pattern_evidence(
            pattern, matched_excerpt=result.context_text
        )
        annotated.append(replace(result, text=rendered, context_text=rendered))
    return tuple(annotated)


def _saved_evidence(item: RetrievalEvidence) -> ConversationEvidence:
    return ConversationEvidence(
        evidence_id=item.evidence_id,
        path=item.path,
        heading=item.heading,
        start_line=item.start_line,
        end_line=item.end_line,
        source_hash=item.source_hash,
        chunk_hash=item.chunk_hash,
        excerpt=item.context_text,
        ranking=item.ranking.to_dict(),
    )


def validate_generated_answer(
    answer: GeneratedAnswer, evidence: Sequence[ConversationEvidence]
) -> tuple[ConversationParagraph, ...]:
    if answer.schema_version != 1:
        raise ConversationError("unsupported_answer_schema", "Generated answer schema is unsupported.")
    allowed = {item.evidence_id for item in evidence}
    paragraphs: list[ConversationParagraph] = []
    for item in answer.paragraphs:
        if not item.citations:
            raise ConversationError("ungrounded_answer", "Every generated paragraph requires a citation.")
        unknown = sorted(set(item.citations) - allowed)
        if unknown:
            raise ConversationError(
                "invalid_citation", "Generated answer cited nonexistent evidence.", {"citations": unknown}
            )
        paragraphs.append(ConversationParagraph(item.text, item.citations, item.support))
    return tuple(paragraphs)


def stale_evidence(vault_root: Path, evidence: ConversationEvidence) -> ConversationEvidence:
    """Validate saved provenance against canonical Markdown, independent of the model/index."""

    try:
        source = read_vault_markdown(vault_root, evidence.path)
    except VaultAccessError:
        return replace(evidence, stale=True)
    note = chunk_markdown_file(source)
    if note.document.content_hash != evidence.source_hash:
        return replace(evidence, stale=True)
    matches = [
        chunk
        for chunk in note.chunks
        if chunk.chunk_hash == evidence.chunk_hash
        and chunk.heading == evidence.heading
        and chunk.start_line == evidence.start_line
        and chunk.end_line == evidence.end_line
    ]
    return replace(evidence, stale=len(matches) != 1)


def refresh_stale_flags(vault_root: Path, turn: ConversationTurn) -> ConversationTurn:
    updated = tuple(stale_evidence(vault_root, item) for item in turn.evidence)
    diagnostics = tuple(turn.diagnostics)
    if any(item.stale for item in updated) and "stale-evidence" not in diagnostics:
        diagnostics = (*diagnostics, "stale-evidence")
    return replace(turn, evidence=updated, diagnostics=diagnostics)


class KnowledgeConversationService:
    def __init__(
        self,
        *,
        vault_root: Path,
        runtime_dir: Path,
        policy: RetrievalPolicy | None = None,
    ) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.artifacts = ConversationArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
        self.retriever = HybridRetriever(vault_root=vault_root, runtime_dir=runtime_dir, policy=policy)
        self.policy = self.retriever.policy

    def create(self, *, title: str, scope: RetrievalScope | None = None, now: datetime | None = None) -> ConversationArtifact:
        return self.artifacts.create(title=title, scope=scope, now=now)

    def ask(
        self,
        relative_path: str,
        *,
        query: str,
        expected_hash: str,
        answer_provider: AnswerProvider | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        evidence_only: bool = False,
        limit: int = 8,
        context_budget: int = 12_000,
        timeout_seconds: float | None = 30.0,
        cancellation: CancellationToken | None = None,
        now: datetime | None = None,
    ) -> ConversationArtifact:
        artifact = self.artifacts.load(relative_path)
        if artifact.content_hash != expected_hash:
            raise ConversationError("stale_artifact", "Conversation changed since it was loaded.")
        if artifact.metadata.status == "archived":
            raise ConversationError("archived_conversation", "Archived conversations cannot accept new turns.")
        scope = replace(
            artifact.metadata.scope,
            pinned_paths=tuple(dict.fromkeys((*artifact.metadata.scope.pinned_paths, *artifact.metadata.pinned_sources))),
            excluded_paths=tuple(dict.fromkeys((*artifact.metadata.scope.excluded_paths, *artifact.metadata.excluded_sources))),
        )
        token = cancellation or CancellationToken()
        archived_patterns = archived_personal_pattern_paths_for_scope(
            vault_root=self.vault_root,
            retrieval_scope=scope,
            explicit_paths=scope.pinned_paths,
        )
        if archived_patterns:
            scope = replace(
                scope,
                excluded_paths=tuple(
                    dict.fromkeys((*scope.excluded_paths, *archived_patterns))
                ),
            )
        response = self.retriever.search(
            RetrievalRequest(
                query=query,
                scope=scope,
                limit=limit,
                context_budget=context_budget,
                timeout_seconds=timeout_seconds,
            ),
            embedding_provider=embedding_provider,
            cancellation=token,
        )
        retrieval_results = response.results
        try:
            local_pattern_context = build_personal_pattern_context(
                vault_root=self.vault_root,
                runtime_dir=self.runtime_dir,
                question=query,
                limit=limit,
                retrieval_scope=scope,
                candidate_paths=(item.path for item in retrieval_results),
                explicit_paths=scope.pinned_paths,
            )
            retrieval_results = _pattern_annotated_results(
                retrieval_results, local_pattern_context
            )
        except PersonalPatternContextError:
            retrieval_results = tuple(
                item for item in retrieval_results if not item.path.startswith("patterns/")
            )
        evidence = tuple(_saved_evidence(item) for item in retrieval_results)
        state = "ready"
        paragraphs: tuple[ConversationParagraph, ...] = ()
        explanation = ""
        diagnostics = list(response.diagnostics)
        disclosure = response.provider_disclosure.to_dict()
        if not evidence:
            state = "no-results" if response.state == "no-results" else "degraded"
            explanation = "The selected vault scope does not contain enough evidence."
        elif evidence_only:
            state = "evidence-only"
            paragraphs = tuple(
                ConversationParagraph(item.excerpt, (item.evidence_id,), "direct") for item in evidence
            )
            explanation = "Evidence-only mode returned source passages without model synthesis."
        elif answer_provider is None:
            state = "unavailable-provider"
            explanation = "Evidence is available, but no answer provider is configured."
        else:
            provider_results = retrieval_results
            local_pattern_paths = {
                item.path for item in retrieval_results if item.path.startswith("patterns/")
            }
            if local_pattern_paths:
                try:
                    external_pattern_context = build_personal_pattern_context(
                        vault_root=self.vault_root,
                        runtime_dir=self.runtime_dir,
                        question=query,
                        limit=limit,
                        mode="external",
                        retrieval_scope=scope,
                        candidate_paths=local_pattern_paths,
                        explicit_paths=scope.pinned_paths,
                    )
                    external_paths = {
                        item.pattern_path for item in external_pattern_context.items
                    }
                    provider_results = _pattern_annotated_results(
                        tuple(
                            item
                            for item in provider_results
                            if item.path not in local_pattern_paths or item.path in external_paths
                        ),
                        external_pattern_context,
                    )
                except PersonalPatternContextError:
                    provider_results = tuple(
                        item for item in provider_results if item.path not in local_pattern_paths
                    )
            answer_evidence = tuple(item.answer_evidence() for item in provider_results)
            generation_disclosure = build_provider_disclosure(
                evidence=answer_evidence,
                capabilities=answer_provider.capabilities,
                scope=scope,
                policy=self.policy,
            )
            disclosure = generation_disclosure.to_dict()
            if not generation_disclosure.allowed:
                state = "degraded"
                diagnostics.append(f"generation:{generation_disclosure.reason}")
                explanation = "The configured privacy policy blocked generation for this evidence."
            else:
                try:
                    generated = answer_provider.generate(
                        query,
                        answer_evidence,
                        timeout_seconds=timeout_seconds,
                        cancellation=token,
                    )
                    paragraphs = validate_generated_answer(generated, evidence)
                    explanation = generated.explanation
                except ProviderError as exc:
                    state = "timeout" if exc.code == "timeout" else "malformed-response"
                    diagnostics.append(f"generation:{exc.code}:{exc.message}")
                    explanation = "The answer provider did not return a usable grounded answer."
                except ConversationError as exc:
                    state = "malformed-response"
                    diagnostics.append(f"generation:{exc.code}:{exc.message}")
                    explanation = "Citation validation rejected the generated answer."
        moment = _moment(now)
        turn = ConversationTurn(
            _turn_id(artifact),
            moment.isoformat(),
            query,
            state,  # type: ignore[arg-type]
            evidence,
            paragraphs,
            explanation,
            disclosure,
            tuple(diagnostics),
        )
        return self.artifacts.append_turn(
            relative_path, turn, expected_hash=expected_hash, now=moment
        )

    def stale_status(self, relative_path: str) -> tuple[ConversationTurn, ...]:
        artifact = self.artifacts.load(relative_path)
        return tuple(refresh_stale_flags(self.vault_root, turn) for turn in artifact.turns)
