from dataclasses import dataclass

from lifeos.ingestion.provenance import ProvenanceGenerator


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    path: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class WikiProposalContent:
    title: str
    body: str
    generator: ProvenanceGenerator
