"""Resumable rich-capture processing, merge, and split operations."""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

from .artifact import CaptureArtifactService, utc_now
from .contracts import CaptureArtifact, CaptureError
from .extraction import ExtractionCancellation, LocalExtractionService
from .storage import AttachmentStore


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
    capture_type: str
    attachment_ids: tuple[str, ...]
    link_paths: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CaptureProcessingService:
    def __init__(self, *, vault_root: Path, runtime_dir: Path) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.captures = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
        self.store = AttachmentStore(vault_root=vault_root, runtime_dir=runtime_dir)
        self.extractor = LocalExtractionService(vault_root=vault_root, runtime_dir=runtime_dir)

    def start_extraction(self, capture_path: str, *, expected_hash: str, now: datetime | None = None) -> ProcessingJob:
        artifact = self.captures.load(capture_path)
        if artifact.content_hash != expected_hash:
            raise CaptureError("stale_capture", "Capture changed before processing started.")
        moment = utc_now(now)
        job = ProcessingJob(f"job-{secrets.token_hex(8)}", capture_path, tuple(item.attachment_id for item in artifact.metadata.attachments), "queued", created_at=moment.isoformat(), updated_at=moment.isoformat())
        self._write_job(job)
        if artifact.metadata.state != "processing":
            self.captures.transition(capture_path, "processing", expected_hash=artifact.content_hash, reason="extraction started", now=moment)
        return job

    def run_extraction(self, job_id: str, *, cancellation: ExtractionCancellation | None = None, now: datetime | None = None) -> ProcessingJob:
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
                self._write_job(replace(running, completed_attachment_ids=tuple(completed), failed_attachment_ids=tuple(failed), updated_at=utc_now(now).isoformat()))
        except CaptureError as exc:
            state = "cancelled" if exc.code == "cancelled" else "failed"
            stopped = replace(running, state=state, completed_attachment_ids=tuple(completed), failed_attachment_ids=tuple(failed), updated_at=utc_now(now).isoformat())
            self._write_job(stopped)
            return stopped
        final_state = "completed" if not failed else "needs-review"
        final = replace(running, state=final_state, completed_attachment_ids=tuple(completed), failed_attachment_ids=tuple(failed), updated_at=utc_now(now).isoformat())
        self._write_job(final)
        artifact = self.captures.load(job.capture_path)
        target = "enriched" if final_state == "completed" else "needs-review"
        if artifact.metadata.state == "processing":
            self.captures.transition(artifact.path, target, expected_hash=artifact.content_hash, reason="extraction finished", now=utc_now(now))
        return final

    def retry(self, job_id: str, *, now: datetime | None = None) -> ProcessingJob:
        job = self.load_job(job_id)
        retry = replace(job, state="queued", failed_attachment_ids=(), updated_at=utc_now(now).isoformat())
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
            raise CaptureError("merge_requires_multiple", "At least two captures are required for a merge.")
        artifacts = tuple(self.captures.load(path) for path in source_paths)
        attachments = tuple(dict.fromkeys(ref.attachment_id for item in artifacts for ref in item.metadata.attachments))
        links = tuple(dict.fromkeys(link.path for item in artifacts for link in item.metadata.links))
        types = {item.metadata.capture_type for item in artifacts}
        return MergePreview(source_paths, tuple(item.content_hash for item in artifacts), " + ".join(item.metadata.title for item in artifacts), next(iter(types)) if len(types) == 1 else "mixed", attachments, links, ("Human annotations from every source will be copied into the merged capture.",))

    def apply_merge(self, preview: MergePreview, *, now: datetime | None = None) -> CaptureArtifact:
        artifacts = tuple(self.captures.load(path) for path in preview.source_paths)
        if tuple(item.content_hash for item in artifacts) != preview.source_hashes:
            raise CaptureError("stale_merge", "A source capture changed after merge preview.")
        unique_refs = {ref.attachment_id: ref for item in artifacts for ref in item.metadata.attachments}
        unique_links = {(link.path, link.relation): link for item in artifacts for link in item.metadata.links}
        merged = self.captures.create(title=preview.title, capture_type=preview.capture_type, description="\n\n".join(item.metadata.description for item in artifacts if item.metadata.description), event_at=datetime.fromisoformat(min(item.metadata.event_at for item in artifacts)), source_entry_point="capture-merge", attachments=tuple(unique_refs.values()), links=tuple(unique_links.values()), now=now)
        target = self.vault_root / merged.path
        source_notes = "\n\n".join(f"### {item.metadata.title}\n\n{item.human_body.strip()}" for item in artifacts)
        target.write_text(target.read_text().rstrip() + f"\n\n## Merged source annotations\n\n{source_notes}\n")
        merged = self.captures.load(merged.path)
        metadata = replace(merged.metadata, merged_from=tuple(item.metadata.capture_id for item in artifacts))
        merged = self.captures.save(merged, metadata, expected_hash=merged.content_hash)
        for item in artifacts:
            current = self.captures.load(item.path)
            if current.metadata.state != "archived":
                self.captures.transition(current.path, "archived", expected_hash=current.content_hash, reason=f"merged into {merged.metadata.capture_id}", now=now)
        return merged

    def split(self, source_path: str, groups: tuple[tuple[str, ...], ...], *, expected_hash: str, now: datetime | None = None) -> tuple[CaptureArtifact, ...]:
        source = self.captures.load(source_path)
        if source.content_hash != expected_hash:
            raise CaptureError("stale_split", "Source capture changed after split was prepared.")
        known = {ref.attachment_id: ref for ref in source.metadata.attachments}
        used = [item for group in groups for item in group]
        if len(used) != len(set(used)) or any(item not in known for item in used):
            raise CaptureError("invalid_split", "Split groups contain duplicate or unknown attachments.")
        results = []
        for index, group in enumerate(groups, 1):
            created = self.captures.create(title=f"{source.metadata.title} {index}", capture_type=source.metadata.capture_type, description=source.metadata.description, event_at=datetime.fromisoformat(source.metadata.event_at), timezone_name=source.metadata.timezone, source_entry_point="capture-split", privacy_scope=source.metadata.privacy_scope, sensitive=source.metadata.sensitive, attachments=tuple(known[item] for item in group), links=source.metadata.links, tags=source.metadata.tags, now=now)
            results.append(self.captures.save(created, replace(created.metadata, split_from=source.metadata.capture_id), expected_hash=created.content_hash))
        current = self.captures.load(source.path)
        self.captures.transition(current.path, "archived", expected_hash=current.content_hash, reason="split into new captures", now=now)
        return tuple(results)

    def _write_job(self, job: ProcessingJob) -> None:
        root = self.runtime_dir / "captures" / "jobs"
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{job.job_id}.json").write_text(json.dumps(job.to_dict(), indent=2, sort_keys=True) + "\n")
