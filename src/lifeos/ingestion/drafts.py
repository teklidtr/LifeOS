from dataclasses import dataclass

from lifeos.ingestion.provenance import ProvenanceGenerator


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    path: str
    content_hash: str
    tags: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WikiProposalContent:
    title: str
    body: str
    generator: ProvenanceGenerator
    tags: tuple[str, ...] = ()
    tag_rationale: str | None = None
