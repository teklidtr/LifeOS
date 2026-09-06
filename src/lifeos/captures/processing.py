"""Resumable rich-capture processing, merge, and split operations."""

from __future__ import annotations

import json
import hashlib
import secrets
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

from .artifact import CaptureArtifactService, PreparedCapture, utc_now
from .contracts import (
    CaptureArtifact,
    CaptureError,
    CaptureState,
    CaptureType,
    ProvenanceRecord,
)
from .extraction import ExtractionCancellation, LocalExtractionService
from .storage import AttachmentStore
from .transaction import (
    CaptureFileWrite,
    CaptureTransactionError,
    execute_capture_transaction,
    idempotency_key_hash,
    recover_capture_transactions,
)


@dataclass(frozen=True, slots=True)
class ProcessingJob:
    job_id: str
    capture_path: str
    attachment_ids: tuple[str, ...]
    state: str
    completed_attachment_ids: tuple[str, ...] = ()
    failed_attachment_ids: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MergePreview:
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    title: str
    capture_type: CaptureType
    attachment_ids: tuple[str, ...]
    link_paths: tuple[str, ...]
    warnings: tuple[str, ...]
    fingerprint: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_CAPTURE_TYPES = frozenset({"meal", "exercise", "attachment", "mixed"})
_PRIVACY_ORDER = {"standard": 0, "private": 1, "protected": 2}


def _request_fingerprint(value: dict[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _preview_payload(preview: MergePreview) -> dict[str, object]:
    return {
        "source_paths": list(preview.source_paths),
        "source_hashes": list(preview.source_hashes),
        "title": preview.title,
        "capture_type": preview.capture_type,
        "attachment_ids": list(preview.attachment_ids),
        "link_paths": list(preview.link_paths),
        "warnings": list(preview.warnings),
    }


def _capture_id_suffix(operation_token: str, index: int) -> str:
    return hashlib.sha256(f"{operation_token}\0{index}".encode("utf-8")).hexdigest()[:8]


def _capture_id(moment: datetime, operation_token: str, index: int) -> str:
    suffix = _capture_id_suffix(operation_token, index)
    return f"cap-{moment.strftime('%Y%m%dT%H%M%SZ')}-{suffix}"


def _transaction_error(error: CaptureTransactionError) -> CaptureError:
    return CaptureError(error.code, error.message, error.data)


class CaptureProcessingService:
    def __init__(self, *, vault_root: Path, runtime_dir: Path) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.captures = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
        self.store = AttachmentStore(vault_root=vault_root, runtime_dir=runtime_dir)
        self.extractor = LocalExtractionService(vault_root=vault_root, runtime_dir=runtime_dir)

    def start_extraction(
        self, capture_path: str, *, expected_hash: str, now: datetime | None = None
    ) -> ProcessingJob:
        artifact = self.captures.load(capture_path)
        if artifact.content_hash != expected_hash:
            raise CaptureError("stale_capture", "Capture changed before processing started.")
        moment = utc_now(now)
        job = ProcessingJob(
            f"job-{secrets.token_hex(8)}",
            capture_path,
            tuple(item.attachment_id for item in artifact.metadata.attachments),
            "queued",
            created_at=moment.isoformat(),
            updated_at=moment.isoformat(),
        )
        self._write_job(job)
        if artifact.metadata.state != "processing":
            self.captures.transition(
                capture_path,
                "processing",
                expected_hash=artifact.content_hash,
                reason="extraction started",
                now=moment,
            )
        return job

    def run_extraction(
        self,
        job_id: str,
        *,
        cancellation: ExtractionCancellation | None = None,
        now: datetime | None = None,
    ) -> ProcessingJob:
        job = self.load_job(job_id)
        token = cancellation or ExtractionCancellation()
        completed = list(job.completed_attachment_ids)
        failed = list(job.failed_attachment_ids)
        running = replace(job, state="processing", updated_at=utc_now(now).isoformat())
        self._write_job(running)
        try:
            for attachment_id in job.attachment_ids:
                if attachment_id in completed:
                    continue
                token.checkpoint()
                manifest = self.store.manifests.load(f"attachments/manifests/{attachment_id}.md")
                result = self.extractor.extract(manifest.metadata, cancellation=token)
                self.extractor.publish(result)
                if result.status in {"completed", "unavailable"}:
                    completed.append(attachment_id)
                else:
                    failed.append(attachment_id)
                self._write_job(
                    replace(
                        running,
                        completed_attachment_ids=tuple(completed),
                        failed_attachment_ids=tuple(failed),
                        updated_at=utc_now(now).isoformat(),
                    )
                )
        except CaptureError as exc:
            state = "cancelled" if exc.code == "cancelled" else "failed"
            stopped = replace(
                running,
                state=state,
                completed_attachment_ids=tuple(completed),
                failed_attachment_ids=tuple(failed),
                updated_at=utc_now(now).isoformat(),
            )
            self._write_job(stopped)
            return stopped
        final_state = "completed" if not failed else "needs-review"
        final = replace(
            running,
            state=final_state,
            completed_attachment_ids=tuple(completed),
            failed_attachment_ids=tuple(failed),
            updated_at=utc_now(now).isoformat(),
        )
        self._write_job(final)
        artifact = self.captures.load(job.capture_path)
        target: CaptureState = "enriched" if final_state == "completed" else "needs-review"
        if artifact.metadata.state == "processing":
            self.captures.transition(
                artifact.path,
                target,
                expected_hash=artifact.content_hash,
                reason="extraction finished",
                now=utc_now(now),
            )
        return final

    def cancel(self, job_id: str, *, now: datetime | None = None) -> ProcessingJob:
        job = self.load_job(job_id)
        if job.state in {"completed", "cancelled"}:
            return job
        cancelled = replace(job, state="cancelled", updated_at=utc_now(now).isoformat())
        self._write_job(cancelled)
        return cancelled

    def retry(self, job_id: str, *, now: datetime | None = None) -> ProcessingJob:
        job = self.load_job(job_id)
        retry = replace(
            job, state="queued", failed_attachment_ids=(), updated_at=utc_now(now).isoformat()
        )
        self._write_job(retry)
        return retry

    def load_job(self, job_id: str) -> ProcessingJob:
        target = self.runtime_dir / "captures" / "jobs" / f"{job_id}.json"
        if not target.exists():
            raise CaptureError("job_not_found", "Processing job was not found.")
        data = json.loads(target.read_text())
        data["attachment_ids"] = tuple(data["attachment_ids"])
        data["completed_attachment_ids"] = tuple(data["completed_attachment_ids"])
        data["failed_attachment_ids"] = tuple(data["failed_attachment_ids"])
        return ProcessingJob(**data)

    def merge_preview(self, source_paths: tuple[str, ...]) -> MergePreview:
        if len(source_paths) < 2:
            raise CaptureError(
                "merge_requires_multiple", "At least two captures are required for a merge."
            )
        if len(source_paths) != len(set(source_paths)):
            raise CaptureError("invalid_merge", "A merge source may appear only once.")
        artifacts = tuple(self.captures.load(path) for path in source_paths)
        return self._merge_preview_from_artifacts(artifacts)

    def _merge_preview_from_artifacts(self, artifacts: tuple[CaptureArtifact, ...]) -> MergePreview:
        attachments = tuple(
            dict.fromkeys(
                ref.attachment_id for item in artifacts for ref in item.metadata.attachments
            )
        )
        links = tuple(
            dict.fromkeys(link.path for item in artifacts for link in item.metadata.links)
        )
        types = {item.metadata.capture_type for item in artifacts}
        preview = MergePreview(
            tuple(item.path for item in artifacts),
            tuple(item.content_hash for item in artifacts),
            " + ".join(item.metadata.title for item in artifacts),
            next(iter(types)) if len(types) == 1 else "mixed",
            attachments,
            links,
            ("Human annotations from every source will be copied into the merged capture.",),
        )
        return replace(preview, fingerprint=_request_fingerprint(_preview_payload(preview)))

    def apply_merge(
        self,
        preview: MergePreview,
        *,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> CaptureArtifact:
        if len(preview.source_paths) < 2 or len(preview.source_paths) != len(
            set(preview.source_paths)
        ):
            raise CaptureError(
                "invalid_merge", "A merge requires at least two unique source captures."
            )
        if len(preview.source_hashes) != len(preview.source_paths):
            raise CaptureError(
                "invalid_merge_preview", "Merge preview sources and hashes do not align."
            )
        if preview.capture_type not in _CAPTURE_TYPES:
            raise CaptureError("invalid_merge_preview", "Merge preview capture type is invalid.")
        supplied_fingerprint = _request_fingerprint(_preview_payload(preview))
        if preview.fingerprint and preview.fingerprint != supplied_fingerprint:
            raise CaptureError(
                "invalid_merge_preview", "Merge preview fields do not match its fingerprint."
            )
        selected_fingerprint = preview.fingerprint or supplied_fingerprint
        key = idempotency_key or f"auto-{selected_fingerprint.removeprefix('sha256:')[:32]}"
        try:
            key_hash = idempotency_key_hash(key)
            recover_capture_transactions(vault_root=self.vault_root, runtime_dir=self.runtime_dir)
        except CaptureTransactionError as error:
            raise _transaction_error(error) from error
        artifacts = tuple(self.captures.load(path) for path in preview.source_paths)
        existing = self._existing_mutation_results(
            operation="merge",
            key_hash=key_hash,
            request_fingerprint=selected_fingerprint,
            source_artifacts=artifacts,
            source_hashes=preview.source_hashes,
            groups=None,
        )
        if existing is not None:
            return existing[0]

        if tuple(item.content_hash for item in artifacts) != preview.source_hashes:
            raise CaptureError("stale_merge", "A source capture changed after merge preview.")
        expected_preview = self._merge_preview_from_artifacts(artifacts)
        normalized_preview = replace(preview, fingerprint=expected_preview.fingerprint)
        if normalized_preview != expected_preview:
            raise CaptureError(
                "invalid_merge_preview", "Merge preview no longer matches its canonical sources."
            )
        moment = utc_now(now)
        unique_refs = {
            ref.attachment_id: ref for item in artifacts for ref in item.metadata.attachments
        }
        unique_links = {
            (link.path, link.relation): link for item in artifacts for link in item.metadata.links
        }
        privacy_scope = max(
            (item.metadata.privacy_scope for item in artifacts),
            key=lambda value: _PRIVACY_ORDER[value],
        )
        source_notes = "\n\n".join(
            f"### {item.metadata.title}\n\n{item.human_body.strip()}" for item in artifacts
        )
        marker = self._mutation_marker("merge", key_hash, selected_fingerprint, index=1, total=1)
        operation_token = f"merge\0{key_hash}\0{selected_fingerprint}"
        merged = self.captures.prepare_create(
            title=preview.title,
            capture_type=preview.capture_type,
            description="\n\n".join(
                item.metadata.description for item in artifacts if item.metadata.description
            ),
            event_at=datetime.fromisoformat(min(item.metadata.event_at for item in artifacts)),
            timezone_name=min(artifacts, key=lambda item: item.metadata.event_at).metadata.timezone,
            source_entry_point=marker,
            privacy_scope=privacy_scope,
            sensitive=any(item.metadata.sensitive for item in artifacts),
            attachments=tuple(unique_refs.values()),
            links=tuple(unique_links.values()),
            tags=tuple(dict.fromkeys(tag for item in artifacts for tag in item.metadata.tags)),
            exclude_from_semantic=any(item.metadata.exclude_from_semantic for item in artifacts),
            exclude_from_conversations=any(
                item.metadata.exclude_from_conversations for item in artifacts
            ),
            exclude_from_reviews=any(item.metadata.exclude_from_reviews for item in artifacts),
            exclude_from_experiments=any(
                item.metadata.exclude_from_experiments for item in artifacts
            ),
            capture_id=_capture_id(moment, operation_token, 1),
            merged_from=tuple(item.metadata.capture_id for item in artifacts),
            human_body=(
                f"## User annotations\n\n\n## Merged source annotations\n\n{source_notes}\n"
            ),
            now=moment,
        )
        archived_sources = tuple(
            self.captures.prepare_transition(
                item,
                "archived",
                reason=f"merged into {merged.artifact.metadata.capture_id}",
                provenance_record=ProvenanceRecord(
                    "capture-mutation",
                    self._source_mutation_marker(
                        "merge",
                        key_hash,
                        selected_fingerprint,
                        index=index,
                        total=len(artifacts),
                        result_ids=(merged.artifact.metadata.capture_id,),
                    ),
                    moment.isoformat(),
                    "Source archived by an atomic capture merge.",
                    item.content_hash,
                ),
                now=moment,
            )
            for index, item in enumerate(artifacts, 1)
        )
        writes = (
            CaptureFileWrite(merged.artifact.path, merged.content.encode("utf-8")),
            *(
                CaptureFileWrite(
                    prepared.artifact.path,
                    prepared.content.encode("utf-8"),
                    expected_hash=source.content_hash,
                )
                for source, prepared in zip(artifacts, archived_sources, strict=True)
            ),
        )
        try:
            receipt = execute_capture_transaction(
                vault_root=self.vault_root,
                runtime_dir=self.runtime_dir,
                operation="merge",
                idempotency_key=key,
                request_fingerprint=selected_fingerprint,
                result_paths=(merged.artifact.path,),
                writes=tuple(writes),
            )
        except CaptureTransactionError as error:
            code = "stale_merge" if error.code == "stale_capture" else error.code
            raise CaptureError(code, error.message, error.data) from error
        if len(receipt.result_paths) != 1:
            raise CaptureError("recovery_required", "Merge transaction result is incomplete.")
        return self.captures.load(receipt.result_paths[0])

    def split(
        self,
        source_path: str,
        groups: tuple[tuple[str, ...], ...],
        *,
        expected_hash: str,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> tuple[CaptureArtifact, ...]:
        if len(groups) < 2 or any(not group for group in groups):
            raise CaptureError(
                "invalid_split", "Split requires at least two non-empty attachment groups."
            )
        request_fingerprint = _request_fingerprint(
            {
                "source_path": source_path,
                "source_hash": expected_hash,
                "groups": [list(group) for group in groups],
            }
        )
        key = idempotency_key or f"auto-{request_fingerprint.removeprefix('sha256:')[:32]}"
        try:
            key_hash = idempotency_key_hash(key)
            recover_capture_transactions(vault_root=self.vault_root, runtime_dir=self.runtime_dir)
        except CaptureTransactionError as error:
            raise _transaction_error(error) from error
        source = self.captures.load(source_path)
        existing = self._existing_mutation_results(
            operation="split",
            key_hash=key_hash,
            request_fingerprint=request_fingerprint,
            source_artifacts=(source,),
            source_hashes=(expected_hash,),
            groups=groups,
        )
        if existing is not None:
            return existing

        if source.content_hash != expected_hash:
            raise CaptureError("stale_split", "Source capture changed after split was prepared.")
        known = {ref.attachment_id: ref for ref in source.metadata.attachments}
        used = [item for group in groups for item in group]
        if len(used) != len(set(used)) or any(item not in known for item in used):
            raise CaptureError(
                "invalid_split", "Split groups contain duplicate or unknown attachments."
            )
        moment = utc_now(now)
        results: list[PreparedCapture] = []
        operation_token = f"split\0{key_hash}\0{request_fingerprint}"
        for index, group in enumerate(groups, 1):
            created = self.captures.prepare_create(
                title=f"{source.metadata.title} {index}",
                capture_type=source.metadata.capture_type,
                description=source.metadata.description,
                event_at=datetime.fromisoformat(source.metadata.event_at),
                timezone_name=source.metadata.timezone,
                source_entry_point=self._mutation_marker(
                    "split",
                    key_hash,
                    request_fingerprint,
                    index=index,
                    total=len(groups),
                ),
                privacy_scope=source.metadata.privacy_scope,
                sensitive=source.metadata.sensitive,
                attachments=tuple(known[item] for item in group),
                links=source.metadata.links,
                tags=source.metadata.tags,
                exclude_from_semantic=source.metadata.exclude_from_semantic,
                exclude_from_conversations=source.metadata.exclude_from_conversations,
                exclude_from_reviews=source.metadata.exclude_from_reviews,
                exclude_from_experiments=source.metadata.exclude_from_experiments,
                capture_id=_capture_id(moment, operation_token, index),
                split_from=source.metadata.capture_id,
                now=moment,
            )
            results.append(created)
        result_ids = tuple(item.artifact.metadata.capture_id for item in results)
        archived_source = self.captures.prepare_transition(
            source,
            "archived",
            reason=f"split into {', '.join(result_ids)}",
            provenance_record=ProvenanceRecord(
                "capture-mutation",
                self._source_mutation_marker(
                    "split",
                    key_hash,
                    request_fingerprint,
                    index=1,
                    total=1,
                    result_ids=result_ids,
                ),
                moment.isoformat(),
                "Source archived by an atomic capture split.",
                source.content_hash,
            ),
            now=moment,
        )
        writes = (
            *(
                CaptureFileWrite(item.artifact.path, item.content.encode("utf-8"))
                for item in results
            ),
            CaptureFileWrite(
                archived_source.artifact.path,
                archived_source.content.encode("utf-8"),
                expected_hash=source.content_hash,
            ),
        )
        try:
            receipt = execute_capture_transaction(
                vault_root=self.vault_root,
                runtime_dir=self.runtime_dir,
                operation="split",
                idempotency_key=key,
                request_fingerprint=request_fingerprint,
                result_paths=tuple(item.artifact.path for item in results),
                writes=tuple(writes),
            )
        except CaptureTransactionError as error:
            code = "stale_split" if error.code == "stale_capture" else error.code
            raise CaptureError(code, error.message, error.data) from error
        return tuple(self.captures.load(path) for path in receipt.result_paths)

    @staticmethod
    def _mutation_marker(
        operation: str,
        key_hash: str,
        request_fingerprint: str,
        *,
        index: int,
        total: int,
    ) -> str:
        return ":".join(
            (
                "capture-mutation",
                operation,
                key_hash,
                request_fingerprint.removeprefix("sha256:"),
                str(index),
                str(total),
            )
        )

    @staticmethod
    def _source_mutation_marker(
        operation: str,
        key_hash: str,
        request_fingerprint: str,
        *,
        index: int,
        total: int,
        result_ids: tuple[str, ...],
    ) -> str:
        return ":".join(
            (
                "capture-mutation-source",
                operation,
                key_hash,
                request_fingerprint.removeprefix("sha256:"),
                str(index),
                str(total),
                ",".join(result_ids),
            )
        )

    @staticmethod
    def _lineage_error(message: str) -> CaptureError:
        return CaptureError("recovery_required", message)

    def _validate_created_mutation_result(
        self,
        artifact: CaptureArtifact,
        *,
        operation: str,
        key_hash: str,
        request_fingerprint: str,
        index: int,
        total: int,
    ) -> None:
        marker = self._mutation_marker(
            operation,
            key_hash,
            request_fingerprint,
            index=index,
            total=total,
        )
        metadata = artifact.metadata
        try:
            created_at = datetime.fromisoformat(metadata.created_at)
        except ValueError as error:
            raise self._lineage_error(
                "A canonical mutation result has an invalid creation timestamp."
            ) from error
        operation_token = f"{operation}\0{key_hash}\0{request_fingerprint}"
        if (
            metadata.source_entry_point != marker
            or metadata.capture_id != _capture_id(created_at, operation_token, index)
            or metadata.captured_at != metadata.created_at
            or not metadata.provenance
            or metadata.provenance[0].kind != "capture"
            or metadata.provenance[0].source != marker
            or metadata.provenance[0].recorded_at != metadata.created_at
            or not metadata.lifecycle
            or metadata.lifecycle[0].from_state is not None
            or metadata.lifecycle[0].to_state != "captured"
            or metadata.lifecycle[0].occurred_at != metadata.created_at
        ):
            raise self._lineage_error(
                "A canonical mutation result does not have valid creation lineage."
            )

    def _validate_source_archive(
        self,
        source: CaptureArtifact,
        *,
        operation: str,
        key_hash: str,
        request_fingerprint: str,
        source_hash: str,
        index: int,
        total: int,
        result_ids: tuple[str, ...],
        result_created_at: str,
        reason: str,
    ) -> None:
        marker = self._source_mutation_marker(
            operation,
            key_hash,
            request_fingerprint,
            index=index,
            total=total,
            result_ids=result_ids,
        )
        records = tuple(
            item
            for item in source.metadata.provenance
            if item.kind == "capture-mutation"
            and item.source == marker
            and item.source_hash == source_hash
        )
        if len(records) != 1 or records[0].recorded_at != result_created_at:
            raise self._lineage_error(
                "A source capture does not have matching mutation provenance."
            )
        events = tuple(
            item
            for item in source.metadata.lifecycle
            if item.to_state == "archived"
            and item.occurred_at == records[0].recorded_at
            and item.reason == reason
        )
        if len(events) != 1:
            raise self._lineage_error(
                "A source capture does not have a matching archive transition."
            )

    def _validate_merge_results(
        self,
        results: tuple[CaptureArtifact, ...],
        *,
        key_hash: str,
        request_fingerprint: str,
        sources: tuple[CaptureArtifact, ...],
        source_hashes: tuple[str, ...],
    ) -> None:
        if len(results) != 1 or len(sources) < 2 or len(sources) != len(source_hashes):
            raise self._lineage_error("A prior merge has an incomplete canonical result set.")
        result = results[0]
        self._validate_created_mutation_result(
            result,
            operation="merge",
            key_hash=key_hash,
            request_fingerprint=request_fingerprint,
            index=1,
            total=1,
        )
        source_ids = tuple(item.metadata.capture_id for item in sources)
        if (
            len(source_ids) != len(set(source_ids))
            or result.metadata.merged_from != source_ids
            or result.metadata.split_from is not None
        ):
            raise self._lineage_error("A prior merge has inconsistent canonical lineage.")
        for index, (source, source_hash) in enumerate(zip(sources, source_hashes, strict=True), 1):
            self._validate_source_archive(
                source,
                operation="merge",
                key_hash=key_hash,
                request_fingerprint=request_fingerprint,
                source_hash=source_hash,
                index=index,
                total=len(sources),
                result_ids=(result.metadata.capture_id,),
                result_created_at=result.metadata.created_at,
                reason=f"merged into {result.metadata.capture_id}",
            )

    def _validate_split_results(
        self,
        results: tuple[CaptureArtifact, ...],
        *,
        key_hash: str,
        request_fingerprint: str,
        source: CaptureArtifact,
        source_hash: str,
        groups: tuple[tuple[str, ...], ...],
    ) -> None:
        if len(results) != len(groups) or len(results) < 2:
            raise self._lineage_error("A prior split has an incomplete canonical result set.")
        for index, result in enumerate(results, 1):
            self._validate_created_mutation_result(
                result,
                operation="split",
                key_hash=key_hash,
                request_fingerprint=request_fingerprint,
                index=index,
                total=len(results),
            )
            if (
                result.metadata.split_from != source.metadata.capture_id
                or result.metadata.merged_from
            ):
                raise self._lineage_error("A prior split has inconsistent canonical lineage.")
        created_at = results[0].metadata.created_at
        if any(item.metadata.created_at != created_at for item in results[1:]):
            raise self._lineage_error("A prior split has inconsistent creation timestamps.")
        result_ids = tuple(item.metadata.capture_id for item in results)
        self._validate_source_archive(
            source,
            operation="split",
            key_hash=key_hash,
            request_fingerprint=request_fingerprint,
            source_hash=source_hash,
            index=1,
            total=1,
            result_ids=result_ids,
            result_created_at=created_at,
            reason=f"split into {', '.join(result_ids)}",
        )

    def _existing_mutation_results(
        self,
        *,
        operation: str,
        key_hash: str,
        request_fingerprint: str,
        source_artifacts: tuple[CaptureArtifact, ...],
        source_hashes: tuple[str, ...],
        groups: tuple[tuple[str, ...], ...] | None,
    ) -> tuple[CaptureArtifact, ...] | None:
        matching_key: list[tuple[CaptureArtifact, tuple[str, ...]]] = []
        matching_sources: list[tuple[CaptureArtifact, tuple[str, ...]]] = []
        for artifact in self.captures.list():
            parts = artifact.metadata.source_entry_point.split(":")
            if len(parts) == 6 and parts[0] == "capture-mutation" and parts[2] == key_hash:
                matching_key.append((artifact, tuple(parts)))
            for record in artifact.metadata.provenance:
                source_parts = record.source.split(":")
                if (
                    record.kind == "capture-mutation"
                    and len(source_parts) >= 3
                    and source_parts[0] == "capture-mutation-source"
                    and source_parts[2] == key_hash
                ):
                    matching_sources.append((artifact, tuple(source_parts)))
        expected_digest = request_fingerprint.removeprefix("sha256:")
        if any(len(parts) != 7 for _, parts in matching_sources):
            raise self._lineage_error("A source capture has malformed mutation provenance.")
        if any(
            parts[1] != operation or parts[3] != expected_digest for _, parts in matching_sources
        ):
            raise CaptureError(
                "idempotency_conflict",
                "Idempotency key was reused for a different capture mutation.",
            )
        expected_source_count = len(source_artifacts) if operation == "merge" else 1
        if matching_sources and len(matching_sources) != expected_source_count:
            raise self._lineage_error("A prior capture mutation has incomplete source provenance.")
        if not matching_key:
            if matching_sources:
                raise self._lineage_error(
                    "A prior capture mutation is missing its canonical result set."
                )
            return None
        if any(parts[1] != operation or parts[3] != expected_digest for _, parts in matching_key):
            raise CaptureError(
                "idempotency_conflict",
                "Idempotency key was reused for a different capture mutation.",
            )
        try:
            totals = {int(parts[5]) for _, parts in matching_key}
            indexed = {int(parts[4]): artifact for artifact, parts in matching_key}
        except ValueError as error:
            raise CaptureError(
                "recovery_required", "A canonical capture has malformed idempotency lineage."
            ) from error
        if len(totals) != 1:
            raise CaptureError(
                "recovery_required", "A prior capture mutation has inconsistent result lineage."
            )
        total = next(iter(totals))
        expected_total = 1 if operation == "merge" else len(groups or ())
        if (
            total != expected_total
            or set(indexed) != set(range(1, expected_total + 1))
            or len(indexed) != len(matching_key)
        ):
            raise CaptureError(
                "recovery_required", "A prior capture mutation has an incomplete result set."
            )
        results = tuple(indexed[index] for index in range(1, total + 1))
        if operation == "merge":
            self._validate_merge_results(
                results,
                key_hash=key_hash,
                request_fingerprint=request_fingerprint,
                sources=source_artifacts,
                source_hashes=source_hashes,
            )
        elif groups is not None and len(source_artifacts) == len(source_hashes) == 1:
            self._validate_split_results(
                results,
                key_hash=key_hash,
                request_fingerprint=request_fingerprint,
                source=source_artifacts[0],
                source_hash=source_hashes[0],
                groups=groups,
            )
        else:
            raise self._lineage_error("A prior split has invalid source lineage.")
        return results

    def _write_job(self, job: ProcessingJob) -> None:
        root = self.runtime_dir / "captures" / "jobs"
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{job.job_id}.json").write_text(
            json.dumps(job.to_dict(), indent=2, sort_keys=True) + "\n"
        )
