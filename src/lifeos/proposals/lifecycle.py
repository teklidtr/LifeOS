import json
import os
import hashlib
import yaml
from dataclasses import dataclass
from typing import Literal, Callable, Any
from pathlib import Path

from .schema import (
    ProposalMetadata,
    ProposalStatus,
    ProposalSchemaError,
    validate_metadata,
    serialize_metadata,
)
from .loader import LoadedProposal
from .patches import AnyPatchDocument, serialize_patch_document
from .review_snapshot import (
    REVIEW_SNAPSHOT_FILENAME,
    ProposalReviewSnapshot,
    serialize_review_snapshot,
)
from .._atomic_write import atomic_write_file_secure, AtomicWriteError
from .._secure_io import open_directory_secure, SecureIOError, read_file_secure


@dataclass(frozen=True)
class ProposalTransitionResult:
    proposal_id: str
    previous_status: ProposalStatus
    new_status: ProposalStatus
    proposal_path: str
    previous_source_hash: str
    new_source_hash: str
    write_occurred: bool
    durability: Literal["confirmed", "uncertain"]
    lock_released: bool


class TransitionError(Exception):
    def __init__(
        self, code: str, field_path: str | None, message: str, write_occurred: bool = False
    ) -> None:
        super().__init__(f"{field_path or '.'} ({code}): {message}")
        self.code = code
        self.field_path = field_path
        self.message = message
        self.write_occurred = write_occurred


class _ProposalSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def _represent_string(dumper: _ProposalSafeDumper, data: str) -> yaml.ScalarNode:
    lower = data.lower()
    ambiguous = {"y", "n", "yes", "no", "true", "false", "on", "off", "null", "~"}
    style = None
    if lower in ambiguous or data == "":
        style = '"'
    else:
        try:
            float(data)
            style = '"'
        except ValueError:
            pass
        if not style:
            import re

            if re.match(r"^\d{4}-\d{2}-\d{2}", data):
                style = '"'
    if "\n" in data or "\r" in data:
        style = '"'
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_ProposalSafeDumper.add_representer(str, _represent_string)


def serialize_proposal_markdown(metadata: ProposalMetadata, body: str) -> bytes:
    meta_dict = serialize_metadata(metadata)
    yaml_text = yaml.dump(
        meta_dict,
        Dumper=_ProposalSafeDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    yaml_text = yaml_text.replace("\r\n", "\n")
    if not yaml_text.endswith("\n"):
        yaml_text += "\n"
    return b"---\n" + yaml_text.encode("utf-8") + b"---\n" + body.encode("utf-8")


def compute_review_digest(
    metadata: ProposalMetadata,
    body: str,
    patch_document: AnyPatchDocument,
    review_snapshot: ProposalReviewSnapshot | None = None,
) -> str:
    env = {
        "review_schema_version": 2 if review_snapshot is not None else 1,
        "metadata": {
            "schema_version": metadata.schema_version,
            "id": metadata.id,
            "title": metadata.title,
            "description": metadata.description,
            "risk": metadata.risk.value,
            "created_at": metadata.created_at,
            "created_by": metadata.created_by,
            "related_goals": list(metadata.related_goals),
            "related_sources": list(metadata.related_sources),
            "patch_schema_version": metadata.patch_schema_version,
            "extensions": serialize_metadata(metadata)["extensions"],
        },
        "body": body,
        "patch_document": serialize_patch_document(patch_document),
    }
    if review_snapshot is not None:
        env["review_snapshot"] = serialize_review_snapshot(review_snapshot)

    digest_bytes = json.dumps(
        env,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    h = hashlib.sha256(digest_bytes).hexdigest()
    return f"sha256:{h}"


def submit_metadata_for_review(
    metadata: ProposalMetadata,
    *,
    submitted_by: str,
    submitted_at: str,
    review_digest: str,
) -> ProposalMetadata:
    if metadata.lifecycle_schema_version is None and metadata.status != ProposalStatus.DRAFT:
        raise TransitionError(
            "legacy_lifecycle_incomplete", None, "Legacy non-draft proposal cannot transition"
        )

    if metadata.status != ProposalStatus.DRAFT:
        raise TransitionError(
            "invalid_transition", "status", f"Cannot submit from {metadata.status.value}"
        )

    d = serialize_metadata(metadata)
    d["status"] = ProposalStatus.PENDING.value
    d["lifecycle_schema_version"] = 1
    d["submitted_by"] = submitted_by
    d["submitted_at"] = submitted_at
    d["review_digest"] = review_digest

    try:
        return validate_metadata(d)
    except ProposalSchemaError as e:
        raise TransitionError("invalid_metadata", e.field_path, e.message) from e


def approve_metadata(
    metadata: ProposalMetadata,
    *,
    approved_by: str,
    approved_at: str,
    current_review_digest: str,
) -> ProposalMetadata:
    if metadata.lifecycle_schema_version is None:
        raise TransitionError(
            "legacy_lifecycle_incomplete", None, "Legacy non-draft proposal cannot transition"
        )

    if metadata.status != ProposalStatus.PENDING:
        raise TransitionError(
            "invalid_transition", "status", f"Cannot approve from {metadata.status.value}"
        )

    if metadata.review_digest != current_review_digest:
        raise TransitionError(
            "review_digest_mismatch",
            "review_digest",
            "Current digest differs from submitted digest",
        )

    d = serialize_metadata(metadata)
    d["status"] = ProposalStatus.APPROVED.value
    d["approved_by"] = approved_by
    d["approved_at"] = approved_at

    try:
        return validate_metadata(d)
    except ProposalSchemaError as e:
        raise TransitionError("invalid_metadata", e.field_path, e.message) from e


def reject_metadata(
    metadata: ProposalMetadata,
    *,
    rejected_by: str,
    rejected_at: str,
    rejection_reason: str,
    current_review_digest: str,
) -> ProposalMetadata:
    if metadata.lifecycle_schema_version is None:
        raise TransitionError(
            "legacy_lifecycle_incomplete", None, "Legacy non-draft proposal cannot transition"
        )

    if metadata.status not in (ProposalStatus.PENDING, ProposalStatus.APPROVED):
        raise TransitionError(
            "invalid_transition", "status", f"Cannot reject from {metadata.status.value}"
        )

    if metadata.review_digest != current_review_digest:
        raise TransitionError(
            "review_digest_mismatch",
            "review_digest",
            "Current digest differs from submitted digest",
        )

    d = serialize_metadata(metadata)
    d["status"] = ProposalStatus.REJECTED.value
    d["rejected_by"] = rejected_by
    d["rejected_at"] = rejected_at
    d["rejection_reason"] = rejection_reason

    try:
        return validate_metadata(d)
    except ProposalSchemaError as e:
        raise TransitionError("invalid_metadata", e.field_path, e.message) from e


def _transition_persistent(
    proposal: LoadedProposal,
    proposals_root: Path,
    mutator: Callable[[ProposalMetadata, str], ProposalMetadata],
) -> ProposalTransitionResult:
    try:
        root_fd = open_directory_secure(proposals_root)
    except SecureIOError as e:
        raise TransitionError("root_open_failed", None, e.message) from e

    try:
        prop_fd = open_directory_secure(Path(proposal.proposal_dir), dir_fd=root_fd)
    except SecureIOError as e:
        os.close(root_fd)
        raise TransitionError("dir_open_failed", None, e.message) from e

    from .._owned_lock import OwnedLock, LockError

    transition_lock = OwnedLock(prop_fd, ".lifeos-transition.lock")
    lock_released = False

    try:
        try:
            transition_lock.acquire()
        except LockError as e:
            raise TransitionError(
                "transition_in_progress", None, "A transition lock already exists"
            ) from e

        def read_review_hash() -> str | None:
            try:
                review_bytes = read_file_secure(
                    REVIEW_SNAPSHOT_FILENAME,
                    Path(proposal.proposal_dir),
                    prop_fd,
                )
            except SecureIOError as error:
                if error.code == "open_failed" and "No such file" in error.message:
                    return None
                raise TransitionError("read_failed", None, error.message) from error
            return f"sha256:{hashlib.sha256(review_bytes).hexdigest()}"

        def verify_review_source(*, timing: str) -> None:
            if read_review_hash() != proposal.review_snapshot_source_hash:
                raise TransitionError(
                    "changed_review_snapshot_source",
                    None,
                    f"{REVIEW_SNAPSHOT_FILENAME} changed {timing}",
                )

        # Re-read and re-hash source
        try:
            md_bytes = read_file_secure("proposal.md", Path(proposal.proposal_dir), prop_fd)
            json_bytes = read_file_secure("patches.json", Path(proposal.proposal_dir), prop_fd)
        except SecureIOError as e:
            raise TransitionError("read_failed", None, e.message) from e

        current_md_hash = f"sha256:{hashlib.sha256(md_bytes).hexdigest()}"
        current_json_hash = f"sha256:{hashlib.sha256(json_bytes).hexdigest()}"

        if current_md_hash != proposal.proposal_source_hash:
            raise TransitionError(
                "stale_proposal_source", None, "proposal.md changed after loading"
            )
        if current_json_hash != proposal.patches_source_hash:
            raise TransitionError(
                "changed_patch_source", None, "patches.json changed after loading"
            )
        verify_review_source(timing="after loading")

        # Re-parse validation
        try:
            md_text = md_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise TransitionError("invalid_utf8", None, "proposal.md is not valid UTF-8")

        from ..markdown.parser import parse_markdown_note

        parsed = parse_markdown_note(Path(proposal.proposal_dir) / "proposal.md", content=md_text)
        if any(f.severity == "error" for f in parsed.findings):
            raise TransitionError("malformed_proposal", None, "proposal.md contains parse errors")

        try:
            current_metadata = validate_metadata(dict(parsed.frontmatter))
        except ProposalSchemaError as e:
            raise TransitionError("invalid_metadata", e.field_path, e.message) from e

        if (
            current_metadata.id != proposal.metadata.id
            or current_metadata.status != proposal.metadata.status
        ):
            raise TransitionError("malformed_proposal", "id/status", "proposal identity changed")

        # Mutate
        current_digest = compute_review_digest(
            current_metadata,
            proposal.body,
            proposal.patch_document,
            proposal.review_snapshot,
        )
        new_metadata = mutator(current_metadata, current_digest)

        # Serialize
        new_md_bytes = serialize_proposal_markdown(new_metadata, proposal.body)

        # Round-trip validate candidate
        parsed_candidate = parse_markdown_note(Path("dummy"), content=new_md_bytes.decode("utf-8"))
        validate_metadata(dict(parsed_candidate.frontmatter))

        def pre_replace_check() -> None:
            try:
                md_b = read_file_secure("proposal.md", Path(proposal.proposal_dir), prop_fd)
                json_b = read_file_secure("patches.json", Path(proposal.proposal_dir), prop_fd)
            except SecureIOError as e:
                raise TransitionError("read_failed", None, e.message) from e

            if f"sha256:{hashlib.sha256(md_b).hexdigest()}" != proposal.proposal_source_hash:
                raise TransitionError(
                    "stale_proposal_source", None, "proposal.md changed immediately before write"
                )
            if f"sha256:{hashlib.sha256(json_b).hexdigest()}" != proposal.patches_source_hash:
                raise TransitionError(
                    "changed_patch_source", None, "patches.json changed immediately before write"
                )
            verify_review_source(timing="immediately before write")

        try:
            durability = atomic_write_file_secure(
                prop_fd,
                "proposal.md",
                new_md_bytes,
                pre_replace_check=pre_replace_check,
            )
        except TransitionError as e:
            raise e
        except AtomicWriteError as e:
            raise TransitionError(
                "atomic_write_failed", None, str(e), write_occurred=e.write_occurred
            ) from e

        new_source_hash = f"sha256:{hashlib.sha256(new_md_bytes).hexdigest()}"

        res_tuple = (
            proposal.metadata.id,
            current_metadata.status,
            new_metadata.status,
            proposal.proposal_path,
            proposal.proposal_source_hash,
            new_source_hash,
            True,
            durability,
        )

    finally:
        lock_release_res = transition_lock.release()
        lock_released = lock_release_res.released if lock_release_res else False
        os.close(prop_fd)
        os.close(root_fd)

    return ProposalTransitionResult(*res_tuple, lock_released=lock_released)


def submit_proposal_for_review(
    proposal: LoadedProposal,
    *,
    proposals_root: Path,
    submitted_by: str,
    submitted_at: str,
) -> ProposalTransitionResult:
    def mutator(meta: ProposalMetadata, digest: str) -> ProposalMetadata:
        return submit_metadata_for_review(
            meta, submitted_by=submitted_by, submitted_at=submitted_at, review_digest=digest
        )

    return _transition_persistent(proposal, proposals_root, mutator)


def approve_proposal(
    proposal: LoadedProposal,
    *,
    proposals_root: Path,
    approved_by: str,
    approved_at: str,
) -> ProposalTransitionResult:
    def mutator(meta: ProposalMetadata, digest: str) -> ProposalMetadata:
        return approve_metadata(
            meta, approved_by=approved_by, approved_at=approved_at, current_review_digest=digest
        )

    return _transition_persistent(proposal, proposals_root, mutator)


def reject_proposal(
    proposal: LoadedProposal,
    *,
    proposals_root: Path,
    rejected_by: str,
    rejected_at: str,
    rejection_reason: str,
) -> ProposalTransitionResult:
    def mutator(meta: ProposalMetadata, digest: str) -> ProposalMetadata:
        return reject_metadata(
            meta,
            rejected_by=rejected_by,
            rejected_at=rejected_at,
            rejection_reason=rejection_reason,
            current_review_digest=digest,
        )

    return _transition_persistent(proposal, proposals_root, mutator)
