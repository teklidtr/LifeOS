import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .._secure_io import SecureIOError, read_file_secure
from ..markdown.parser import parse_markdown_note
from .patches import (
    AnyPatchDocument,
    PatchSchemaError,
    serialize_patch_json_bytes,
    validate_patch_document,
)
from .schema import (
    ProposalMetadata,
    ProposalSchemaError,
    validate_metadata,
    validate_proposal_id,
)


@dataclass(frozen=True)
class ProposalLoadFinding:
    severity: Literal["error", "warning"]
    code: str
    proposal_path: str
    field_path: str | None
    message: str


@dataclass(frozen=True)
class LoadedProposal:
    proposal_dir: str
    proposal_path: str
    patches_path: str
    proposal_source_hash: str
    patches_source_hash: str
    metadata: ProposalMetadata
    patch_document: AnyPatchDocument
    body: str


@dataclass(frozen=True)
class ProposalLoadResult:
    proposal: LoadedProposal | None
    findings: tuple[ProposalLoadFinding, ...]


@dataclass(frozen=True)
class ProposalCollectionResult:
    proposals: tuple[LoadedProposal, ...]
    findings: tuple[ProposalLoadFinding, ...]


def _reject_duplicates(ordered_pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys."""
    d: dict[str, Any] = {}
    for k, v in ordered_pairs:
        if k in d:
            raise ValueError(f"duplicate key: {k}")
        d[k] = v
    return d


def _parse_constant(c: str) -> float:
    """Reject nonstandard JSON numeric constants."""
    raise ValueError(f"nonstandard constant not allowed: {c}")


def _read_secure_wrapper(
    dir_fd: int | None, filename: str | Path, base_path: Path
) -> tuple[bytes | None, ProposalLoadFinding | None]:
    try:
        content = read_file_secure(filename, base_path, dir_fd)
        return content, None
    except SecureIOError as e:
        return None, ProposalLoadFinding(
            severity="error",
            code=e.code,
            proposal_path=str(Path(filename)),
            field_path=None,
            message=e.message,
        )

def _sort_findings(findings: list[ProposalLoadFinding]) -> tuple[ProposalLoadFinding, ...]:
    findings.sort(
        key=lambda f: (
            f.proposal_path,
            f.field_path is not None,
            f.field_path or "",
            f.severity,
            f.code,
            f.message,
        )
    )
    return tuple(findings)


def load_proposal_directory(
    proposal_dir: Path, *, proposals_root: Path
) -> ProposalLoadResult:
    findings: list[ProposalLoadFinding] = []

    if proposal_dir.parent != proposals_root:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="not_immediate_child",
                proposal_path=proposal_dir.name,
                field_path=None,
                message="Proposal directory is not an immediate child of the root",
            )
        )
        return ProposalLoadResult(None, _sort_findings(findings))

    try:
        validate_proposal_id(proposal_dir.name)
    except ProposalSchemaError:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="invalid_directory_name",
                proposal_path=proposal_dir.name,
                field_path=None,
                message="Directory name is not a valid proposal ID",
            )
        )
        return ProposalLoadResult(None, _sort_findings(findings))

    from .._secure_io import open_directory_secure

    try:
        root_fd = open_directory_secure(proposals_root)
    except SecureIOError as e:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="root_open_failed" if e.code == "dir_open_failed" else e.code,
                proposal_path=proposal_dir.name,
                field_path=None,
                message=f"Failed to open root directory: {e.message}",
            )
        )
        return ProposalLoadResult(None, _sort_findings(findings))

    try:
        # Open proposal directory relative to root_fd
        try:
            prop_fd = open_directory_secure(proposal_dir, dir_fd=root_fd)
        except SecureIOError as e:
            findings.append(
                ProposalLoadFinding(
                    severity="error",
                    code="dir_open_failed",
                    proposal_path=proposal_dir.name,
                    field_path=None,
                    message=f"Failed to open proposal directory: {e.message}",
                )
            )
            return ProposalLoadResult(None, _sort_findings(findings))

        try:
            # Check for extra files
            if getattr(os, "scandir") in getattr(os, "supports_dir_fd", set()):
                it = os.scandir(prop_fd)
            else:
                it = os.scandir(str(proposal_dir))
            with it:
                for entry in it:
                    if entry.name not in ("proposal.md", "patches.json"):
                        findings.append(
                            ProposalLoadFinding(
                                severity="warning",
                                code="extra_file",
                                proposal_path=f"{proposal_dir.name}/{entry.name}",
                                field_path=None,
                                message="Unexpected entry in proposal directory",
                            )
                        )

            # Read proposal.md
            md_path = f"{proposal_dir.name}/proposal.md"
            md_bytes, md_finding = _read_secure_wrapper(
                prop_fd if getattr(os, "open") in getattr(os, "supports_dir_fd", set()) else None,
                "proposal.md",
                proposal_dir,
            )
            if md_finding:
                findings.append(
                    ProposalLoadFinding(
                        severity=md_finding.severity,
                        code=md_finding.code,
                        proposal_path=md_path,
                        field_path=md_finding.field_path,
                        message=md_finding.message,
                    )
                )

            # Read patches.json
            json_path = f"{proposal_dir.name}/patches.json"
            json_bytes, json_finding = _read_secure_wrapper(
                prop_fd if getattr(os, "open") in getattr(os, "supports_dir_fd", set()) else None,
                "patches.json",
                proposal_dir,
            )
            if json_finding:
                findings.append(
                    ProposalLoadFinding(
                        severity=json_finding.severity,
                        code=json_finding.code,
                        proposal_path=json_path,
                        field_path=json_finding.field_path,
                        message=json_finding.message,
                    )
                )

        finally:
            os.close(prop_fd)
    finally:
        os.close(root_fd)

    if any(f.severity == "error" for f in findings):
        return ProposalLoadResult(None, _sort_findings(findings))

    assert md_bytes is not None
    assert json_bytes is not None

    # Process proposal.md
    try:
        md_text = md_bytes.decode("utf-8")
    except UnicodeDecodeError:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="invalid_utf8",
                proposal_path=md_path,
                field_path=None,
                message="Markdown file is not valid UTF-8",
            )
        )
        return ProposalLoadResult(None, _sort_findings(findings))

    parsed = parse_markdown_note(proposal_dir / "proposal.md", content=md_text)
    has_md_error = False
    for pf in parsed.findings:
        findings.append(
            ProposalLoadFinding(
                severity=pf.severity,
                code=pf.code,
                proposal_path=md_path,
                field_path=None,
                message=pf.message,
            )
        )
        if pf.severity == "error":
            has_md_error = True

    if has_md_error:
        return ProposalLoadResult(None, _sort_findings(findings))

    try:
        metadata = validate_metadata(dict(parsed.frontmatter))
    except ProposalSchemaError as e:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code=e.code,
                proposal_path=md_path,
                field_path=e.field_path,
                message=e.message,
            )
        )
        return ProposalLoadResult(None, _sort_findings(findings))

    # Process patches.json
    if json_bytes.startswith(b"\xef\xbb\xbf"):
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="invalid_bom",
                proposal_path=json_path,
                field_path=None,
                message="UTF-8 BOM is not allowed",
            )
        )
        return ProposalLoadResult(None, _sort_findings(findings))

    try:
        json_text = json_bytes.decode("utf-8")
    except UnicodeDecodeError:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="invalid_utf8",
                proposal_path=json_path,
                field_path=None,
                message="JSON file is not valid UTF-8",
            )
        )
        return ProposalLoadResult(None, _sort_findings(findings))

    try:
        json_data = json.loads(
            json_text, object_pairs_hook=_reject_duplicates, parse_constant=_parse_constant
        )
    except ValueError as e:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="malformed_json",
                proposal_path=json_path,
                field_path=None,
                message=str(e),
            )
        )
        return ProposalLoadResult(None, _sort_findings(findings))

    try:
        patch_doc = validate_patch_document(json_data)
    except PatchSchemaError as e:
        for err in getattr(e, "errors", [e]):
            findings.append(
                ProposalLoadFinding(
                    severity="error",
                    code=err.code,
                    proposal_path=json_path,
                    field_path=err.field_path,
                    message=err.message,
                )
            )
        return ProposalLoadResult(None, _sort_findings(findings))

    # Check canonical JSON
    canonical_bytes = serialize_patch_json_bytes(patch_doc)
    if canonical_bytes != json_bytes:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="noncanonical_json",
                proposal_path=json_path,
                field_path=None,
                message="JSON bytes do not exactly match canonical representation",
            )
        )
        return ProposalLoadResult(None, _sort_findings(findings))

    # Cross-document invariants
    if metadata.id != proposal_dir.name:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="id_mismatch",
                proposal_path=md_path,
                field_path="id",
                message="Metadata ID does not match directory name",
            )
        )
    if patch_doc.proposal_id != metadata.id:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="id_mismatch",
                proposal_path=json_path,
                field_path="proposal_id",
                message="Patch proposal_id does not match metadata ID",
            )
        )
    if patch_doc.schema_version != metadata.patch_schema_version:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="version_mismatch",
                proposal_path=json_path,
                field_path="schema_version",
                message="Patch schema_version does not match metadata patch_schema_version",
            )
        )

    if any(f.severity == "error" for f in findings):
        return ProposalLoadResult(None, _sort_findings(findings))

    body_str = parsed.body
    if md_text.startswith("---"):
        idx = md_text.find("\n---")
        if idx != -1:
            end_of_fm = idx + 4
            if end_of_fm < len(md_text) and md_text[end_of_fm] == "\r":
                end_of_fm += 1
            if end_of_fm < len(md_text) and md_text[end_of_fm] == "\n":
                end_of_fm += 1
            body_str = md_text[end_of_fm:]

    import hashlib
    proposal_source_hash = f"sha256:{hashlib.sha256(md_bytes).hexdigest()}"
    patches_source_hash = f"sha256:{hashlib.sha256(json_bytes).hexdigest()}"

    proposal = LoadedProposal(
        proposal_dir=proposal_dir.name,
        proposal_path=md_path,
        patches_path=json_path,
        proposal_source_hash=proposal_source_hash,
        patches_source_hash=patches_source_hash,
        metadata=metadata,
        patch_document=patch_doc,
        body=body_str,
    )
    return ProposalLoadResult(proposal, _sort_findings(findings))


def load_proposals(proposals_root: Path) -> ProposalCollectionResult:
    findings: list[ProposalLoadFinding] = []
    proposals: list[LoadedProposal] = []

    try:
        st = os.lstat(str(proposals_root))
        if stat.S_ISLNK(st.st_mode):
            findings.append(
                ProposalLoadFinding(
                    severity="error",
                    code="root_is_symlink",
                    proposal_path="",
                    field_path=None,
                    message="Proposals root is a symlink",
                )
            )
            return ProposalCollectionResult(tuple(proposals), _sort_findings(findings))
        if not stat.S_ISDIR(st.st_mode):
            findings.append(
                ProposalLoadFinding(
                    severity="error",
                    code="root_not_directory",
                    proposal_path="",
                    field_path=None,
                    message="Proposals root is not a directory",
                )
            )
            return ProposalCollectionResult(tuple(proposals), _sort_findings(findings))
    except FileNotFoundError:
        return ProposalCollectionResult((), ())
    except OSError as e:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="root_stat_failed",
                proposal_path="",
                field_path=None,
                message=f"Failed to stat proposals root: {e.strerror}",
            )
        )
        return ProposalCollectionResult(tuple(proposals), _sort_findings(findings))

    try:
        with os.scandir(str(proposals_root)) as it:
            entries = list(it)
    except OSError as e:
        findings.append(
            ProposalLoadFinding(
                severity="error",
                code="root_list_failed",
                proposal_path="",
                field_path=None,
                message=f"Failed to list proposals root: {e.strerror}",
            )
        )
        return ProposalCollectionResult(tuple(proposals), _sort_findings(findings))

    entries.sort(key=lambda e: e.name)

    for entry in entries:
        if entry.is_symlink():
            findings.append(
                ProposalLoadFinding(
                    severity="error",
                    code="symlink_entry",
                    proposal_path=entry.name,
                    field_path=None,
                    message="Root entry is a symlink",
                )
            )
            continue

        if not entry.is_dir():
            findings.append(
                ProposalLoadFinding(
                    severity="warning",
                    code="unexpected_root_file",
                    proposal_path=entry.name,
                    field_path=None,
                    message="Unexpected non-directory entry in root",
                )
            )
            continue

        try:
            validate_proposal_id(entry.name)
        except ProposalSchemaError:
            findings.append(
                ProposalLoadFinding(
                    severity="warning",
                    code="invalid_proposal_name",
                    proposal_path=entry.name,
                    field_path=None,
                    message="Directory name is not a valid proposal ID",
                )
            )
            continue

        res = load_proposal_directory(Path(entry.path), proposals_root=proposals_root)
        findings.extend(res.findings)
        if res.proposal:
            proposals.append(res.proposal)

    return ProposalCollectionResult(tuple(proposals), _sort_findings(findings))
