"""Deterministic retrieval regression fixtures and transparent metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from lifeos.retrieval.contracts import RetrievalRequest
from lifeos.retrieval.search import RetrievalResponse


@dataclass(frozen=True, slots=True)
class RetrievalFixture:
    fixture_id: str
    request: RetrievalRequest
    expected_paths: tuple[str, ...] = ()
    expected_no_answer: bool = False
    k: int = 5


@dataclass(frozen=True, slots=True)
class FixtureResult:
    fixture_id: str
    returned_paths: tuple[str, ...]
    expected_paths: tuple[str, ...]
    recall_at_k: float
    ranking_stable: bool
    references_valid: bool
    duplicates_suppressed: bool
    no_answer_correct: bool


@dataclass(frozen=True, slots=True)
class RetrievalEvaluation:
    fixtures: tuple[FixtureResult, ...]
    mean_recall_at_k: float
    ranking_stability_rate: float
    reference_validity_rate: float
    duplicate_suppression_rate: float
    no_answer_accuracy: float

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "fixtures": [asdict(item) for item in self.fixtures]}


def evaluate_retrieval(
    fixtures: tuple[RetrievalFixture, ...],
    *,
    run: Callable[[RetrievalRequest], RetrievalResponse],
) -> RetrievalEvaluation:
    results: list[FixtureResult] = []
    for fixture in fixtures:
        first = run(fixture.request)
        second = run(fixture.request)
        paths = tuple(item.path for item in first.results[: fixture.k])
        expected = set(fixture.expected_paths)
        recall = 1.0 if not expected else len(expected & set(paths)) / len(expected)
        references_valid = all(
            item.path
            and item.start_line > 0
            and item.end_line >= item.start_line
            and item.chunk_hash.startswith("sha256:")
            for item in first.results
        )
        normalized = [item.chunk_hash for item in first.results]
        duplicates_suppressed = len(normalized) == len(set(normalized))
        no_answer_correct = (not first.results) == fixture.expected_no_answer
        results.append(
            FixtureResult(
                fixture.fixture_id,
                paths,
                fixture.expected_paths,
                recall,
                first.to_dict() == second.to_dict(),
                references_valid,
                duplicates_suppressed,
                no_answer_correct,
            )
        )
    count = len(results) or 1
    return RetrievalEvaluation(
        tuple(results),
        sum(item.recall_at_k for item in results) / count,
        sum(item.ranking_stable for item in results) / count,
        sum(item.references_valid for item in results) / count,
        sum(item.duplicates_suppressed for item in results) / count,
        sum(item.no_answer_correct for item in results) / count,
    )
