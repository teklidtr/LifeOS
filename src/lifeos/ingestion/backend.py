from dataclasses import dataclass
from typing import Protocol

from lifeos.ingestion.provenance import ProvenanceGenerator


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    path: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    source: SourceSnapshot
    markdown_body: str


@dataclass(frozen=True, slots=True)
class WikiPageDraft:
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    draft: WikiPageDraft
    generator: ProvenanceGenerator


class AnalysisBackendError(RuntimeError):
    """Provider-independent analysis failure."""


class AnalysisBackend(Protocol):
    def analyze(self, request: AnalysisRequest, /) -> AnalysisResult:
        ...
