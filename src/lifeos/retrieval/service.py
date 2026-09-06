"""Rebuild, incremental synchronization, embedding, and health orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from lifeos.coherence import CoherenceError
from lifeos.coherence_scoped import runtime_exclusion_prefix
from lifeos.markdown.parser import parse_markdown_note
from lifeos.retrieval.chunking import chunk_markdown_file, reidentify_note
from lifeos.retrieval.contracts import (
    CancellationToken,
    EmbeddingProvider,
    RetrievalError,
    RetrievalPolicy,
    RetrievalScope,
    scope_decision,
)
from lifeos.retrieval.index import INDEX_RELATIVE_PATH, INDEX_SCHEMA_VERSION, RetrievalIndex
from lifeos.retrieval.models import ChunkedNote
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.runtime_scope import build_runtime_exclusion_matcher
from lifeos.scanner import ScannerError, scan_vault
from lifeos.vault import VaultAccessError, VaultMarkdownFile, read_vault_markdown

IndexState = Literal[
    "missing", "healthy", "stale", "building", "interrupted", "corrupt", "incompatible"
]
ProgressSink = Callable[["IndexProgress"], None]
_RELOCATION_PARK_PREFIX = ".lifeos/retrieval-relocations/"
_RELOCATION_STAGE_NAME = "index.sqlite3.relocation-sync"


@dataclass(frozen=True, slots=True)
class IndexProgress:
    operation: str
    status: str
    processed: int
    total: int
    current_path: str | None
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IndexHealth:
    state: IndexState
    active_usable: bool
    schema_version: int | None
    documents: int
    chunks: int
    embeddings: int
    stale_embeddings: int
    missing_embeddings: int
    stale_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]
    orphaned_paths: tuple[str, ...]
    rebuild_status: str | None
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IndexRecoveryPlan:
    state: IndexState
    action: str
    destructive_to_derived_state: bool
    canonical_markdown_affected: bool
    resumable: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IndexResult:
    operation: str
    status: str
    processed: int
    total: int
    created: tuple[str, ...]
    updated: tuple[str, ...]
    renamed: tuple[tuple[str, str], ...]
    deleted: tuple[str, ...]
    skipped: tuple[str, ...]
    diagnostics: tuple[str, ...]
    index_path: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class RetrievalIndexService:
    """Retrieval indexing with deterministic stable-identity coherence.

    A normalized durable ``id:<stable-id>`` document key is used only while that identity is
    unique among policy-visible indexed notes. Duplicate identities use path-derived keys so the
    SQLite primary key cannot hide a canonical note. Source discovery applies runtime exclusion
    and retrieval policy to safe path metadata before Markdown content is opened. Incremental
    stable-ID moves are reserved as a set inside a disposable SQLite staging snapshot, including
    every current destination occupant, and are published atomically only after synchronization
    completes without parked internal paths.
    """

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
        self.root = runtime_dir / "retrieval"
        self.active_path = runtime_dir / INDEX_RELATIVE_PATH
        self.staging_path = self.root / "index.sqlite3.rebuild"
        self.rebuild_state_path = self.root / "rebuild-state.json"
        self.incremental_state_path = self.root / "incremental-state.json"

    def health(self, *, embedding_provider: EmbeddingProvider | None = None) -> IndexHealth:
        rebuild = self._read_state(self.rebuild_state_path)
        status_value = rebuild.get("status")
        rebuild_status = status_value if isinstance(status_value, str) else None
        if not self.active_path.exists():
            state: IndexState = (
                "interrupted"
                if rebuild_status == "interrupted"
                else "building"
                if rebuild_status == "building"
                else "missing"
            )
            return IndexHealth(state, False, None, 0, 0, 0, 0, 0, (), (), (), rebuild_status, ())
        try:
            index = RetrievalIndex(self.active_path, create=False)
        except RetrievalError as exc:
            state = "incompatible" if exc.code == "incompatible_index" else "corrupt"
            return IndexHealth(
                state, False, None, 0, 0, 0, 0, 0, (), (), (), rebuild_status, (exc.message,)
            )
        try:
            counts = index.counts()
            current = self._allowed_sources()
            current_hashes = {item.relative_path: _prefixed(item.content_bytes) for item in current}
            indexed = {item.path: item.content_hash for item in index.documents()}
            stale = tuple(
                sorted(
                    path
                    for path in set(current_hashes) & set(indexed)
                    if current_hashes[path] != indexed[path]
                )
            )
            missing = tuple(sorted(set(current_hashes) - set(indexed)))
            orphaned = tuple(sorted(set(indexed) - set(current_hashes)))
            stale_embeddings = index.stale_embedding_count()
            missing_embeddings = 0
            if embedding_provider is not None:
                embedded = {
                    item.chunk_id for item in index.embeddings(embedding_provider.capabilities)
                }
                missing_embeddings = len({item.chunk_id for item in index.chunks()} - embedded)
            state = (
                "stale"
                if stale or missing or orphaned or stale_embeddings or missing_embeddings
                else "healthy"
            )
            if rebuild_status == "building":
                state = "building"
            elif rebuild_status == "interrupted" and state == "healthy":
                state = "interrupted"
            return IndexHealth(
                state,
                True,
                INDEX_SCHEMA_VERSION,
                counts["documents"],
                counts["chunks"],
                counts["embeddings"],
                stale_embeddings,
                missing_embeddings,
                stale,
                missing,
                orphaned,
                rebuild_status,
                (),
            )
        except (RetrievalError, VaultAccessError) as exc:
            return IndexHealth(
                "stale",
                True,
                INDEX_SCHEMA_VERSION,
                0,
                0,
                0,
                0,
                0,
                (),
                (),
                (),
                rebuild_status,
                (str(exc),),
            )
        finally:
            index.close()

    def rebuild(
        self,
        *,
        cancellation: CancellationToken | None = None,
        progress: ProgressSink | None = None,
        batch_size: int = 64,
        resume: bool = True,
        stop_after: int | None = None,
    ) -> IndexResult:
        sources = self._allowed_sources()
        _ambiguous, expected = _identity_plan(sources)
        if type(batch_size) is not int or batch_size <= 0:
            raise RetrievalError("invalid_batch_size", "batch_size must be positive.")
        token = cancellation or CancellationToken()
        manifest = _manifest_hash(sources)
        prior = self._read_state(self.rebuild_state_path)
        resumable = (
            resume
            and prior.get("status") in {"building", "interrupted"}
            and prior.get("manifest_hash") == manifest
            and self.staging_path.exists()
        )
        if not resumable:
            self.root.mkdir(parents=True, exist_ok=True)
            self.staging_path.unlink(missing_ok=True)
            last_path = None
            processed = 0
        else:
            last_path_value = prior.get("last_path")
            last_path = last_path_value if isinstance(last_path_value, str) else None
            processed_value = prior.get("processed", 0)
            processed = processed_value if isinstance(processed_value, int) else 0
        state = {
            "schema_version": 1,
            "status": "building",
            "manifest_hash": manifest,
            "last_path": last_path,
            "processed": processed,
            "total": len(sources),
            "started_at": prior.get("started_at") if resumable else _now(),
        }
        self._write_state(self.rebuild_state_path, state)
        diagnostics: list[str] = []
        skipped: list[str] = []
        index = RetrievalIndex(self.staging_path)
        try:
            if not resumable:
                index.set_meta("build_status", "building")
            pending = [
                item for item in sources if last_path is None or item.relative_path > last_path
            ]
            for source in pending:
                try:
                    token.checkpoint()
                except RetrievalError:
                    state.update(status="interrupted", interrupted_at=_now())
                    self._write_state(self.rebuild_state_path, state)
                    index.set_meta("build_status", "interrupted")
                    self._emit(
                        progress,
                        "rebuild",
                        "interrupted",
                        processed,
                        len(sources),
                        source.relative_path,
                        diagnostics,
                    )
                    return self._result(
                        "rebuild",
                        "interrupted",
                        processed,
                        len(sources),
                        (),
                        (),
                        (),
                        (),
                        skipped,
                        diagnostics,
                        self.staging_path,
                    )
                try:
                    note = chunk_markdown_file(
                        source, expected_document_id=expected[source.relative_path]
                    )
                    index.replace_note(note)
                    diagnostics.extend(note.diagnostics)
                except RetrievalError as exc:
                    skipped.append(source.relative_path)
                    diagnostics.append(f"{source.relative_path}:{exc.code}:{exc.message}")
                processed += 1
                state.update(last_path=source.relative_path, processed=processed)
                if processed % batch_size == 0:
                    self._write_state(self.rebuild_state_path, state)
                    self._emit(
                        progress,
                        "rebuild",
                        "building",
                        processed,
                        len(sources),
                        source.relative_path,
                        diagnostics,
                    )
                if stop_after is not None and processed >= stop_after:
                    state.update(status="interrupted", interrupted_at=_now())
                    self._write_state(self.rebuild_state_path, state)
                    index.set_meta("build_status", "interrupted")
                    self._emit(
                        progress,
                        "rebuild",
                        "interrupted",
                        processed,
                        len(sources),
                        source.relative_path,
                        diagnostics,
                    )
                    return self._result(
                        "rebuild",
                        "interrupted",
                        processed,
                        len(sources),
                        (),
                        (),
                        (),
                        (),
                        skipped,
                        diagnostics,
                        self.staging_path,
                    )
            index.set_meta("build_status", "complete")
            index.set_meta("built_at", _now())
            index.set_meta("source_manifest_hash", manifest)
        finally:
            index.close()
        self.root.mkdir(parents=True, exist_ok=True)
        os.replace(self.staging_path, self.active_path)
        self.rebuild_state_path.unlink(missing_ok=True)
        self._emit(progress, "rebuild", "complete", len(sources), len(sources), None, diagnostics)
        return self._result(
            "rebuild",
            "complete",
            len(sources),
            len(sources),
            tuple(item.relative_path for item in sources if item.relative_path not in skipped),
            (),
            (),
            (),
            skipped,
            diagnostics,
            self.active_path,
        )

    def incremental_sync(
        self,
        *,
        cancellation: CancellationToken | None = None,
        progress: ProgressSink | None = None,
    ) -> IndexResult:
        if not self.active_path.exists():
            return self.rebuild(cancellation=cancellation, progress=progress)
        sources = self._allowed_sources()
        _ambiguous, expected = _identity_plan(sources)
        source_by_path = {source.relative_path: source for source in sources}
        identity_refresh: set[str] = set()
        original_active_path = self.active_path
        relocation_stage = self.root / _RELOCATION_STAGE_NAME
        relocations: tuple[tuple[str, str, str], ...] = ()
        reservations: tuple[tuple[str, str], ...] = ()
        prior_document_ids: dict[str, str] = {}
        staged = False

        try:
            if original_active_path.exists():
                with RetrievalIndex(original_active_path, create=False) as index:
                    for document in index.documents():
                        canonical_path = _canonical_path_from_parked(document.path)
                        prior_document_ids[canonical_path] = document.document_id
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

            result = self._sync_sources(
                sources=sources,
                expected=expected,
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
                return _suppress_unproven_relocations(
                    result,
                    prior_document_ids=prior_document_ids,
                    expected=expected,
                )

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
                    index.replace_note(
                        chunk_markdown_file(source, expected_document_id=expected[path])
                    )

            if identity_refresh:
                result = replace(
                    result,
                    updated=tuple(sorted(set(result.updated) | identity_refresh)),
                )

            result = _suppress_unproven_relocations(
                result,
                prior_document_ids=prior_document_ids,
                expected=expected,
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
            self.active_path = original_active_path
            if staged:
                relocation_stage.unlink(missing_ok=True)

    def _sync_sources(
        self,
        *,
        sources: tuple[VaultMarkdownFile, ...],
        expected: dict[str, str],
        cancellation: CancellationToken | None = None,
        progress: ProgressSink | None = None,
    ) -> IndexResult:
        token = cancellation or CancellationToken()
        source_by_path = {item.relative_path: item for item in sources}
        source_hashes = {
            path: _prefixed(item.content_bytes) for path, item in source_by_path.items()
        }
        diagnostics: list[str] = []
        skipped: list[str] = []
        created: list[str] = []
        updated: list[str] = []
        renamed: list[tuple[str, str]] = []
        deleted: list[str] = []
        index = RetrievalIndex(self.active_path, create=False)
        try:
            existing = {item.path: item for item in index.documents()}
            removed = set(existing) - set(source_by_path)
            added = set(source_by_path) - set(existing)
            changed = {
                path
                for path in set(existing) & set(source_by_path)
                if existing[path].content_hash != source_hashes[path]
            }

            # First preserve identity across unambiguous equal-content renames.
            by_hash_removed: dict[str, list[str]] = {}
            for path in removed:
                by_hash_removed.setdefault(existing[path].content_hash, []).append(path)
            for new_path in sorted(tuple(added)):
                candidates = by_hash_removed.get(source_hashes[new_path], [])
                if len(candidates) == 1:
                    old_path = candidates[0]
                    note = reidentify_note(
                        chunk_markdown_file(
                            source_by_path[new_path], expected_document_id=expected[new_path]
                        ),
                        existing[old_path].document_id,
                    )
                    index.rename_path(old_path, note)
                    removed.remove(old_path)
                    added.remove(new_path)
                    renamed.append((old_path, new_path))

            # Then preserve a durable frontmatter identity across a move that also edited content.
            prepared_added: dict[str, ChunkedNote] = {}
            for new_path in sorted(tuple(added)):
                note = chunk_markdown_file(
                    source_by_path[new_path], expected_document_id=expected[new_path]
                )
                prepared_added[new_path] = note
                candidate = next(
                    (
                        old_path
                        for old_path in sorted(removed)
                        if existing[old_path].document_id == note.document.document_id
                    ),
                    None,
                )
                if candidate is not None:
                    index.rename_path(candidate, note)
                    removed.remove(candidate)
                    added.remove(new_path)
                    renamed.append((candidate, new_path))

            operations = len(removed) + len(added) + len(changed)
            processed = 0
            self._write_state(
                self.incremental_state_path,
                {
                    "schema_version": 1,
                    "status": "running",
                    "started_at": _now(),
                    "processed": 0,
                    "total": operations,
                },
            )
            for path in sorted(removed):
                token.checkpoint()
                index.delete_path(path)
                deleted.append(path)
                processed += 1
                self._sync_progress(progress, processed, operations, path, diagnostics)
            for path, kind in [(path, "created") for path in sorted(added)] + [
                (path, "updated") for path in sorted(changed)
            ]:
                try:
                    token.checkpoint()
                    note = prepared_added.get(path) or chunk_markdown_file(
                        source_by_path[path], expected_document_id=expected[path]
                    )
                    # A durable ID can prove a move even when edited during the move.
                    prior_same_id = next(
                        (
                            item
                            for item in index.documents()
                            if item.document_id == note.document.document_id and item.path != path
                        ),
                        None,
                    )
                    if prior_same_id is not None:
                        index.rename_path(prior_same_id.path, note)
                        renamed.append((prior_same_id.path, path))
                        if prior_same_id.path in removed:
                            removed.remove(prior_same_id.path)
                    else:
                        index.replace_note(note)
                        (created if kind == "created" else updated).append(path)
                    diagnostics.extend(note.diagnostics)
                except RetrievalError as exc:
                    if exc.code == "cancelled":
                        raise
                    skipped.append(path)
                    diagnostics.append(f"{path}:{exc.code}:{exc.message}")
                processed += 1
                self._sync_progress(progress, processed, operations, path, diagnostics)
            self.incremental_state_path.unlink(missing_ok=True)
            return self._result(
                "incremental",
                "complete",
                processed,
                operations,
                created,
                updated,
                renamed,
                deleted,
                skipped,
                diagnostics,
                self.active_path,
            )
        except RetrievalError as exc:
            self._write_state(
                self.incremental_state_path,
                {
                    "schema_version": 1,
                    "status": "interrupted",
                    "interrupted_at": _now(),
                    "reason": exc.code,
                },
            )
            if exc.code == "cancelled":
                return self._result(
                    "incremental",
                    "interrupted",
                    0,
                    0,
                    created,
                    updated,
                    renamed,
                    deleted,
                    skipped,
                    diagnostics,
                    self.active_path,
                )
            raise
        finally:
            index.close()

    def embed_missing(
        self,
        provider: EmbeddingProvider,
        *,
        cancellation: CancellationToken | None = None,
        progress: ProgressSink | None = None,
        batch_size: int | None = None,
        timeout_seconds: float | None = 30.0,
    ) -> IndexResult:
        token = cancellation or CancellationToken()
        if provider.capabilities.kind != "embedding":
            raise RetrievalError("invalid_provider", "Provider does not support embeddings.")
        limit = min(
            batch_size or provider.capabilities.max_batch_size, provider.capabilities.max_batch_size
        )
        if limit <= 0:
            raise RetrievalError("invalid_batch_size", "Embedding batch size must be positive.")
        index = RetrievalIndex(self.active_path, create=False)
        try:
            existing = {item.chunk_id for item in index.embeddings(provider.capabilities)}
            missing = [item for item in index.chunks() if item.chunk_id not in existing]
            processed = 0
            for offset in range(0, len(missing), limit):
                token.checkpoint()
                batch_chunks = missing[offset : offset + limit]
                batch = provider.embed(
                    [item.text for item in batch_chunks],
                    timeout_seconds=timeout_seconds,
                    cancellation=token,
                )
                index.write_embeddings(chunks=batch_chunks, batch=batch, created_at=_now())
                processed += len(batch_chunks)
                self._emit(
                    progress,
                    "embedding",
                    "running",
                    processed,
                    len(missing),
                    batch_chunks[-1].path if batch_chunks else None,
                    (),
                )
            self._emit(progress, "embedding", "complete", processed, len(missing), None, ())
            return self._result(
                "embedding",
                "complete",
                processed,
                len(missing),
                (),
                (),
                (),
                (),
                (),
                (),
                self.active_path,
            )
        finally:
            index.close()

    def recovery_plan(self) -> IndexRecoveryPlan:
        health = self.health()
        if health.state == "healthy":
            return IndexRecoveryPlan(
                health.state,
                "none",
                False,
                False,
                False,
                "The active index matches canonical Markdown.",
            )
        if health.state == "stale":
            return IndexRecoveryPlan(
                health.state,
                "incremental-sync",
                False,
                False,
                True,
                "Synchronize changed, moved, and deleted notes.",
            )
        if health.state == "interrupted" and self.staging_path.exists():
            return IndexRecoveryPlan(
                health.state,
                "resume-rebuild",
                False,
                False,
                True,
                "Resume the staged rebuild without publishing partial state.",
            )
        if health.state in {"corrupt", "incompatible"}:
            return IndexRecoveryPlan(
                health.state,
                "discard-and-rebuild",
                True,
                False,
                False,
                "Delete only disposable retrieval data and rebuild from Markdown.",
            )
        return IndexRecoveryPlan(
            health.state,
            "full-rebuild",
            True,
            False,
            False,
            "Build disposable retrieval data from canonical Markdown.",
        )

    def recover(
        self,
        *,
        cancellation: CancellationToken | None = None,
        progress: ProgressSink | None = None,
    ) -> IndexResult:
        plan = self.recovery_plan()
        if plan.action == "none":
            health = self.health()
            return self._result(
                "recovery",
                "complete",
                0,
                0,
                (),
                (),
                (),
                (),
                (),
                health.diagnostics,
                self.active_path,
            )
        if plan.action == "incremental-sync":
            return self.incremental_sync(cancellation=cancellation, progress=progress)
        if plan.action == "resume-rebuild":
            return self.rebuild(cancellation=cancellation, progress=progress, resume=True)
        if plan.action == "discard-and-rebuild":
            self.discard()
        return self.rebuild(cancellation=cancellation, progress=progress, resume=False)

    def discard(self) -> tuple[str, ...]:
        removed: list[str] = []
        for path in (
            self.active_path,
            self.staging_path,
            self.rebuild_state_path,
            self.incremental_state_path,
        ):
            if path.exists():
                path.unlink()
                removed.append(str(path.relative_to(self.runtime_dir)))
        return tuple(removed)

    def _allowed_sources(self) -> tuple[VaultMarkdownFile, ...]:
        try:
            runtime_prefix = runtime_exclusion_prefix(
                self.vault_root,
                runtime_dir=self.runtime_dir,
            )
            runtime_excluded = build_runtime_exclusion_matcher(
                self.vault_root,
                runtime_dir=self.runtime_dir,
                snapshot_prefix=runtime_prefix,
            )
            default_scope = RetrievalScope()

            def allowed_path(path: str) -> bool:
                if path == "conversations" or path.startswith("conversations/"):
                    return False
                if path == "proposals" or path.startswith("proposals/"):
                    return False
                if runtime_excluded(path):
                    return False
                return scope_decision(
                    path,
                    scope=default_scope,
                    policy=self.policy,
                    mode="local",
                ).allowed

            entries = scan_vault(self.vault_root, path_filter=allowed_path)
        except (CoherenceError, ScannerError) as exc:
            raise RetrievalError("source_unavailable", str(exc)) from exc

        sources: list[VaultMarkdownFile] = []
        for entry in entries:
            if entry.file_type != ".md":
                continue
            path = entry.path.as_posix()
            try:
                if not allowed_path(path):
                    continue
            except CoherenceError as exc:
                raise RetrievalError("source_unavailable", str(exc)) from exc
            try:
                sources.append(read_vault_markdown(self.vault_root, path))
            except VaultAccessError as exc:
                raise RetrievalError("source_unavailable", str(exc)) from exc
        return tuple(sources)

    def _sync_progress(
        self,
        sink: ProgressSink | None,
        processed: int,
        total: int,
        path: str,
        diagnostics: Sequence[str],
    ) -> None:
        self._write_state(
            self.incremental_state_path,
            {
                "schema_version": 1,
                "status": "running",
                "updated_at": _now(),
                "processed": processed,
                "total": total,
                "current_path": path,
            },
        )
        self._emit(sink, "incremental", "running", processed, total, path, diagnostics)

    @staticmethod
    def _emit(
        sink: ProgressSink | None,
        operation: str,
        status: str,
        processed: int,
        total: int,
        path: str | None,
        diagnostics: Sequence[str],
    ) -> None:
        if sink is not None:
            sink(IndexProgress(operation, status, processed, total, path, tuple(diagnostics[-20:])))

    @staticmethod
    def _result(
        operation: str,
        status: str,
        processed: int,
        total: int,
        created: Sequence[str],
        updated: Sequence[str],
        renamed: Sequence[tuple[str, str]],
        deleted: Sequence[str],
        skipped: Sequence[str],
        diagnostics: Sequence[str],
        path: Path,
    ) -> IndexResult:
        return IndexResult(
            operation,
            status,
            processed,
            total,
            tuple(created),
            tuple(updated),
            tuple(renamed),
            tuple(deleted),
            tuple(skipped),
            tuple(diagnostics),
            str(path),
        )

    @staticmethod
    def _read_state(path: Path) -> dict[str, object]:
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {"status": "corrupt"}
        return value if isinstance(value, dict) else {"status": "corrupt"}

    @staticmethod
    def _write_state(path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)


def _prefixed(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _manifest_hash(sources: Sequence[VaultMarkdownFile]) -> str:
    digest = hashlib.sha256()
    for source in sources:
        digest.update(source.relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(source.content_bytes).digest())
    return "sha256:" + digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        document_id for document_id, paths in paths_by_document_id.items() if len(paths) > 1
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
        chunk.path for chunk in index.chunks() if chunk.path.startswith(_RELOCATION_PARK_PREFIX)
    )
    if leaked:
        paths = ", ".join(sorted(leaked))
        raise RetrievalError(
            "relocation_sync_incomplete",
            "Retrieval identity relocation left disposable parked paths in staging: " + paths,
        )


def _restore_public_paths(result: IndexResult) -> IndexResult:
    renamed = tuple(
        (_canonical_path_from_parked(old_path), new_path) for old_path, new_path in result.renamed
    )
    deleted = tuple(_canonical_path_from_parked(path) for path in result.deleted)
    return replace(result, renamed=renamed, deleted=deleted)


def _suppress_unproven_relocations(
    result: IndexResult,
    *,
    prior_document_ids: dict[str, str],
    expected: dict[str, str],
) -> IndexResult:
    """Expose rename evidence only when the same durable ID proves path continuity."""
    retained: list[tuple[str, str]] = []
    demoted_old: set[str] = set()
    demoted_new: set[str] = set()
    for old_path, new_path in result.renamed:
        prior_id = prior_document_ids.get(old_path)
        expected_id = expected.get(new_path)
        if prior_id is not None and prior_id.startswith("id:") and expected_id == prior_id:
            retained.append((old_path, new_path))
            continue
        demoted_old.add(old_path)
        demoted_new.add(new_path)

    if not demoted_old and not demoted_new:
        return result
    return replace(
        result,
        created=tuple(sorted(set(result.created) | demoted_new)),
        updated=tuple(path for path in result.updated if path not in demoted_new),
        renamed=tuple(retained),
        deleted=tuple(sorted(set(result.deleted) | demoted_old)),
    )
