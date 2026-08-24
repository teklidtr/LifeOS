"""Retrieval-index identity reconciliation for durable note IDs."""

from __future__ import annotations

import hashlib
from contextvars import ContextVar
from dataclasses import replace

from lifeos.markdown.parser import parse_markdown_note
from lifeos.retrieval import service as _service
from lifeos.retrieval.chunking import chunk_markdown_file as _base_chunk_markdown_file
from lifeos.retrieval.chunking import reidentify_note
from lifeos.retrieval.index import RetrievalIndex
from lifeos.retrieval.models import ChunkedNote
from lifeos.vault import VaultMarkdownFile

_AMBIGUOUS_DOCUMENT_IDS: ContextVar[frozenset[str]] = ContextVar(
    "lifeos_ambiguous_retrieval_document_ids",
    default=frozenset(),
)


def _path_document_id(path: str) -> str:
    return "path:" + hashlib.sha256(path.encode("utf-8")).hexdigest()


def _durable_document_id(source: VaultMarkdownFile) -> str | None:
    parsed = parse_markdown_note(source.path, content=source.content)
    stable_id = parsed.durable_fields.id
    if stable_id is None:
        return None
    stable_id = stable_id.strip()
    return f"id:{stable_id}" if stable_id else None


def _identity_plan(
    sources: tuple[VaultMarkdownFile, ...],
) -> tuple[frozenset[str], dict[str, str]]:
    paths_by_document_id: dict[str, list[str]] = {}
    source_document_ids: dict[str, str | None] = {}
    for source in sources:
        document_id = _durable_document_id(source)
        source_document_ids[source.relative_path] = document_id
        if document_id is not None:
            paths_by_document_id.setdefault(document_id, []).append(source.relative_path)

    ambiguous = frozenset(
        document_id
        for document_id, paths in paths_by_document_id.items()
        if len(paths) > 1
    )
    expected = {
        source.relative_path: (
            document_id
            if document_id is not None and document_id not in ambiguous
            else _path_document_id(source.relative_path)
        )
        for source in sources
        for document_id in (source_document_ids[source.relative_path],)
    }
    return ambiguous, expected


def _coherent_chunk_markdown_file(
    source: VaultMarkdownFile,
    **kwargs: object,
) -> ChunkedNote:
    note = _base_chunk_markdown_file(source, **kwargs)
    if note.document.document_id in _AMBIGUOUS_DOCUMENT_IDS.get():
        return reidentify_note(note, _path_document_id(source.relative_path))
    return note


class RetrievalIndexService(_service.RetrievalIndexService):
    """Base retrieval service plus deterministic duplicate-ID handling.

    A durable ``id:<stable-id>`` document key is used only while that identity is unique among
    policy-visible indexed notes. If the identity is duplicated, every colliding note gets a
    path-derived document key so the SQLite primary key cannot silently hide one of them. The
    expected key map is reconciled even when canonical content bytes did not change, allowing
    duplicate introduction/resolution to update disposable identity metadata incrementally.
    """

    _coherence_sources: tuple[VaultMarkdownFile, ...] | None = None

    def _allowed_sources(self) -> tuple[VaultMarkdownFile, ...]:
        if self._coherence_sources is not None:
            return self._coherence_sources
        return super()._allowed_sources()

    def rebuild(self, **kwargs: object) -> _service.IndexResult:
        sources = super()._allowed_sources()
        ambiguous, _expected = _identity_plan(sources)
        token = _AMBIGUOUS_DOCUMENT_IDS.set(ambiguous)
        self._coherence_sources = sources
        try:
            return super().rebuild(**kwargs)
        finally:
            self._coherence_sources = None
            _AMBIGUOUS_DOCUMENT_IDS.reset(token)

    def incremental_sync(self, **kwargs: object) -> _service.IndexResult:
        sources = super()._allowed_sources()
        ambiguous, expected = _identity_plan(sources)
        source_by_path = {source.relative_path: source for source in sources}
        identity_refresh: set[str] = set()
        if self.active_path.exists():
            with RetrievalIndex(self.active_path, create=False) as index:
                for document in index.documents():
                    expected_id = expected.get(document.path)
                    if expected_id is not None and document.document_id != expected_id:
                        identity_refresh.add(document.path)

        token = _AMBIGUOUS_DOCUMENT_IDS.set(ambiguous)
        self._coherence_sources = sources
        try:
            result = super().incremental_sync(**kwargs)
            if result.status != "complete" or not self.active_path.exists():
                return result

            # New duplicate introduction can require re-identifying an unchanged existing note;
            # duplicate resolution can likewise restore a durable key without a content edit.
            with RetrievalIndex(self.active_path, create=False) as index:
                current_by_path = {document.path: document for document in index.documents()}
                for path, expected_id in expected.items():
                    current = current_by_path.get(path)
                    if current is not None and current.document_id != expected_id:
                        identity_refresh.add(path)
                for path in sorted(identity_refresh):
                    source = source_by_path.get(path)
                    if source is None:
                        continue
                    index.replace_note(_coherent_chunk_markdown_file(source))

            if not identity_refresh:
                return result
            return replace(
                result,
                updated=tuple(sorted(set(result.updated) | identity_refresh)),
            )
        finally:
            self._coherence_sources = None
            _AMBIGUOUS_DOCUMENT_IDS.reset(token)


# Base service methods resolve this module-level name at call time, so one wrapper keeps rebuild
# and incremental behavior aligned without duplicating the mature indexing implementation.
setattr(_service, "chunk_markdown_file", _coherent_chunk_markdown_file)
