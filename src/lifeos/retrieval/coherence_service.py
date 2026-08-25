"""Retrieval-index identity reconciliation for durable note IDs."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from lifeos.coherence import CoherenceError
from lifeos.coherence_scoped import runtime_exclusion_prefix
from lifeos.markdown.parser import parse_markdown_note
from lifeos.retrieval import service as _service
from lifeos.retrieval.chunking import chunk_markdown_file as _base_chunk_markdown_file
from lifeos.retrieval.chunking import reidentify_note
from lifeos.retrieval.contracts import (
    CancellationToken,
    RetrievalError,
    RetrievalScope,
    scope_decision,
)
from lifeos.retrieval.index import RetrievalIndex
from lifeos.retrieval.models import ChunkedNote
from lifeos.scanner import ScannerError, scan_vault
from lifeos.vault import VaultAccessError, VaultMarkdownFile, read_vault_markdown

_EXPECTED_DOCUMENT_IDS: ContextVar[dict[str, str] | None] = ContextVar(
    "lifeos_expected_retrieval_document_ids",
    default=None,
)
_RELOCATION_PARK_PREFIX = ".lifeos/retrieval-relocations/"
_RELOCATION_STAGE_NAME = "index.sqlite3.relocation-sync"


def _path_document_id(path: str) -> str:
    return "path:" + hashlib.sha256(path.encode("utf-8")).hexdigest()


def _durable_document_id(source: VaultMarkdownFile) -> str | None:
    # The root bootstrap instruction file is control metadata, not a canonical note identity.
    # It may remain searchable evidence, but any frontmatter id on it must not enter the durable
    # note-ID namespace used for relocation semantics.
    if source.relative_path == "AGENTS.md":
        return None
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
    *,
    indexed_at: datetime | None = None,
    max_chunk_characters: int = 1_800,
) -> ChunkedNote:
    note = _base_chunk_markdown_file(
        source,
        indexed_at=indexed_at,
        max_chunk_characters=max_chunk_characters,
    )
    expected = _EXPECTED_DOCUMENT_IDS.get()
    expected_id = expected.get(source.relative_path) if expected is not None else None
    if expected_id is not None and note.document.document_id != expected_id:
        return reidentify_note(note, expected_id)
    return note


def _canonical_path_from_parked(path: str) -> str:
    if not path.startswith(_RELOCATION_PARK_PREFIX):
        return path
    remainder = path[len(_RELOCATION_PARK_PREFIX) :]
    _reservation, separator, canonical_path = remainder.partition("/")
    return canonical_path if separator and canonical_path else path


def _parked_path(document_id: str, prior_path: str) -> str:
    canonical_path = _canonical_path_from_parked(prior_path)
    reservation = hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:16]
    return f"{_RELOCATION_PARK_PREFIX}{reservation}/{canonical_path}"


def _identity_relocations(
    index: RetrievalIndex,
    expected: dict[str, str],
) -> tuple[tuple[str, str, str], ...]:
    documents = index.documents()
    by_id = {
        document.document_id: document
        for document in documents
        if document.document_id.startswith("id:")
    }
    moves: list[tuple[str, str, str]] = []
    for target_path, expected_id in sorted(expected.items()):
        if not expected_id.startswith("id:"):
            continue
        current = by_id.get(expected_id)
        if current is None or current.path == target_path:
            continue
        moves.append((expected_id, current.path, target_path))
    return tuple(moves)


def _relocation_reservations(
    index: RetrievalIndex,
    moves: tuple[tuple[str, str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Reserve moving IDs plus every current occupant of their destination paths."""
    documents = index.documents()
    by_path = {document.path: document for document in documents}
    reservations: dict[str, str] = {
        document_id: old_path for document_id, old_path, _target_path in moves
    }
    for document_id, _old_path, target_path in moves:
        occupant = by_path.get(target_path)
        if occupant is None or occupant.document_id == document_id:
            continue
        reservations.setdefault(occupant.document_id, occupant.path)
    return tuple(sorted(reservations.items(), key=lambda item: (item[1], item[0])))


def _stage_index_snapshot(index: RetrievalIndex, destination: Path) -> None:
    """Copy one consistent active SQLite snapshot into disposable relocation staging."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    try:
        with sqlite3.connect(destination) as staging_connection:
            index.connection.backup(staging_connection)
    except (OSError, sqlite3.DatabaseError) as exc:
        destination.unlink(missing_ok=True)
        raise RetrievalError(
            "relocation_stage_failed",
            f"Could not stage the retrieval index for identity relocation: {exc}",
        ) from exc


def _park_identity_relocations(
    index: RetrievalIndex,
    reservations: tuple[tuple[str, str], ...],
) -> None:
    """Reserve a complete relocation destination set inside the staged index."""
    if not reservations:
        return
    with index.transaction():
        for document_id, old_path in reservations:
            parked = _parked_path(document_id, old_path)
            index.connection.execute(
                "UPDATE documents SET path = ? WHERE document_id = ?",
                (parked, document_id),
            )
            index.connection.execute(
                "UPDATE chunks SET path = ? WHERE document_id = ?",
                (parked, document_id),
            )


def _assert_no_parked_paths(index: RetrievalIndex) -> None:
    leaked = {
        document.path
        for document in index.documents()
        if document.path.startswith(_RELOCATION_PARK_PREFIX)
    }
    leaked.update(
        chunk.path
        for chunk in index.chunks()
        if chunk.path.startswith(_RELOCATION_PARK_PREFIX)
    )
    if leaked:
        paths = ", ".join(sorted(leaked))
        raise RetrievalError(
            "relocation_sync_incomplete",
            "Retrieval identity relocation left disposable parked paths in staging: " + paths,
        )


def _restore_public_paths(result: _service.IndexResult) -> _service.IndexResult:
    renamed = tuple(
        (_canonical_path_from_parked(old_path), new_path)
        for old_path, new_path in result.renamed
    )
    deleted = tuple(_canonical_path_from_parked(path) for path in result.deleted)
    return replace(result, renamed=renamed, deleted=deleted)


class RetrievalIndexService(_service.RetrievalIndexService):
    """Base retrieval service plus deterministic stable-identity coherence.

    A normalized durable ``id:<stable-id>`` document key is used only while that identity is
    unique among policy-visible indexed notes. Duplicate identities use path-derived keys so the
    SQLite primary key cannot hide a canonical note. Source discovery applies runtime exclusion
    and retrieval policy to safe path metadata before Markdown content is opened. Incremental
    stable-ID moves are reserved as a set inside a disposable SQLite staging snapshot, including
    every current destination occupant, and are published atomically only after synchronization
    completes without parked internal paths.
    """

    _coherence_sources: tuple[VaultMarkdownFile, ...] | None = None

    def _allowed_sources(self) -> tuple[VaultMarkdownFile, ...]:
        if self._coherence_sources is not None:
            return self._coherence_sources
        try:
            runtime_prefix = runtime_exclusion_prefix(
                self.vault_root,
                runtime_dir=self.runtime_dir,
            )
            entries = scan_vault(self.vault_root)
        except (CoherenceError, ScannerError) as exc:
            raise RetrievalError("source_unavailable", str(exc)) from exc

        sources: list[VaultMarkdownFile] = []
        for entry in entries:
            if entry.file_type != ".md":
                continue
            path = entry.path.as_posix()
            if path.startswith("conversations/") or path.startswith("proposals/"):
                continue
            if runtime_prefix is not None and path.startswith(runtime_prefix):
                continue
            decision = scope_decision(
                path,
                scope=RetrievalScope(),
                policy=self.policy,
                mode="local",
            )
            if not decision.allowed:
                continue
            try:
                sources.append(read_vault_markdown(self.vault_root, path))
            except VaultAccessError as exc:
                raise RetrievalError("source_unavailable", str(exc)) from exc
        return tuple(sources)

    def rebuild(
        self,
        *,
        cancellation: CancellationToken | None = None,
        progress: _service.ProgressSink | None = None,
        batch_size: int = 64,
        resume: bool = True,
        stop_after: int | None = None,
    ) -> _service.IndexResult:
        sources = self._allowed_sources()
        _ambiguous, expected = _identity_plan(sources)
        token = _EXPECTED_DOCUMENT_IDS.set(expected)
        self._coherence_sources = sources
        try:
            return super().rebuild(
                cancellation=cancellation,
                progress=progress,
                batch_size=batch_size,
                resume=resume,
                stop_after=stop_after,
            )
        finally:
            self._coherence_sources = None
            _EXPECTED_DOCUMENT_IDS.reset(token)

    def incremental_sync(
        self,
        *,
        cancellation: CancellationToken | None = None,
        progress: _service.ProgressSink | None = None,
    ) -> _service.IndexResult:
        sources = self._allowed_sources()
        _ambiguous, expected = _identity_plan(sources)
        source_by_path = {source.relative_path: source for source in sources}
        identity_refresh: set[str] = set()
        original_active_path = self.active_path
        relocation_stage = self.root / _RELOCATION_STAGE_NAME
        relocations: tuple[tuple[str, str, str], ...] = ()
        reservations: tuple[tuple[str, str], ...] = ()
        staged = False

        try:
            if original_active_path.exists():
                with RetrievalIndex(original_active_path, create=False) as index:
                    for document in index.documents():
                        canonical_path = _canonical_path_from_parked(document.path)
                        expected_id = expected.get(canonical_path)
                        if expected_id is not None and document.document_id != expected_id:
                            identity_refresh.add(canonical_path)
                    relocations = _identity_relocations(index, expected)
                    if relocations:
                        reservations = _relocation_reservations(index, relocations)
                        _stage_index_snapshot(index, relocation_stage)
                        staged = True

            if staged:
                self.active_path = relocation_stage
                with RetrievalIndex(self.active_path, create=False) as staged_index:
                    _park_identity_relocations(staged_index, reservations)

            token = _EXPECTED_DOCUMENT_IDS.set(expected)
            self._coherence_sources = sources
            try:
                result = super().incremental_sync(
                    cancellation=cancellation,
                    progress=progress,
                )
                if staged:
                    result = _restore_public_paths(result)
                if result.status != "complete" or not self.active_path.exists():
                    if staged:
                        return replace(
                            result,
                            created=(),
                            updated=(),
                            renamed=(),
                            deleted=(),
                            index_path=str(original_active_path),
                        )
                    return result

                # Duplicate introduction/resolution and normalized durable IDs can require
                # re-identifying an unchanged note even when canonical content did not change.
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

                if identity_refresh:
                    result = replace(
                        result,
                        updated=tuple(sorted(set(result.updated) | identity_refresh)),
                    )

                if staged:
                    with RetrievalIndex(self.active_path, create=False) as staged_index:
                        _assert_no_parked_paths(staged_index)
                    try:
                        os.replace(self.active_path, original_active_path)
                    except OSError as exc:
                        raise RetrievalError(
                            "relocation_publish_failed",
                            f"Could not publish the staged retrieval relocation index: {exc}",
                        ) from exc
                    result = replace(result, index_path=str(original_active_path))
                return result
            finally:
                self._coherence_sources = None
                _EXPECTED_DOCUMENT_IDS.reset(token)
        finally:
            self.active_path = original_active_path
            if staged:
                relocation_stage.unlink(missing_ok=True)


# Base service methods resolve this module-level name at call time, so one wrapper keeps rebuild
# and incremental behavior aligned without duplicating the mature indexing implementation.
setattr(_service, "chunk_markdown_file", _coherent_chunk_markdown_file)