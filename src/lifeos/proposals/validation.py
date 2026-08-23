import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .._secure_io import SecureIOError, hash_file_secure, open_directory_secure, read_file_secure
from ..markdown.parser import parse_markdown_note
from ..ownership import DEFAULT_OWNERSHIP_MANIFEST_PATH
from ..ownership.manifest import GeneratedOwnership, ManifestError
from ..wiki.layout import is_emergent_generated_parent
from .loader import LoadedProposal
from .patches import PatchOperation

PreflightState = Literal["valid", "stale", "invalid"]


@dataclass(frozen=True)
class PreflightFinding:
    severity: Literal["error", "warning"]
    code: str
    operation_id: str | None
    target_path: str | None
    field_path: str | None
    message: str


@dataclass(frozen=True)
class OperationPreflightResult:
    operation_id: str
    target_path: str
    state: PreflightState
    findings: tuple[PreflightFinding, ...]


@dataclass(frozen=True)
class ProposalPreflightResult:
    proposal_id: str
    state: PreflightState
    operations: tuple[OperationPreflightResult, ...]
    findings: tuple[PreflightFinding, ...]


def _sort_findings(findings: list[PreflightFinding]) -> tuple[PreflightFinding, ...]:
    findings.sort(
        key=lambda f: (
            f.target_path is not None,
            f.target_path or "",
            f.operation_id is not None,
            f.operation_id or "",
            f.field_path is not None,
            f.field_path or "",
            f.severity,
            f.code,
            f.message,
        )
    )
    return tuple(findings)


def _aggregate_state(states: list[PreflightState]) -> PreflightState:
    if "invalid" in states:
        return "invalid"
    if "stale" in states:
        return "stale"
    return "valid"


def preflight_proposal(
    proposal: LoadedProposal,
    *,
    vault_root: Path,
    max_inspection_bytes: int = 5 * 1024 * 1024,
) -> ProposalPreflightResult:
    if type(max_inspection_bytes) is not int or max_inspection_bytes <= 0:
        return ProposalPreflightResult(
            proposal_id=proposal.metadata.id,
            state="invalid",
            operations=tuple(
                OperationPreflightResult(
                    operation_id=op.id,
                    target_path=op.target_path,
                    state="invalid",
                    findings=(
                        PreflightFinding(
                            severity="error",
                            code="aborted",
                            operation_id=op.id,
                            target_path=op.target_path,
                            field_path=None,
                            message="Operation aborted due to invalid max_inspection_bytes",
                        ),
                    ),
                )
                for op in proposal.patch_document.operations
            ),
            findings=(
                PreflightFinding(
                    severity="error",
                    code="invalid_inspection_limit",
                    operation_id=None,
                    target_path=None,
                    field_path=None,
                    message="max_inspection_bytes must be a positive integer",
                ),
            ),
        )

    # 1. Securely open vault root
    try:
        root_fd = open_directory_secure(vault_root)
    except SecureIOError:
        ops = tuple(
            OperationPreflightResult(
                operation_id=op.id,
                target_path=op.target_path,
                state="invalid",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="aborted",
                        operation_id=op.id,
                        target_path=op.target_path,
                        field_path=None,
                        message="Operation aborted due to vault root failure",
                    ),
                ),
            )
            for op in proposal.patch_document.operations
        )
        return ProposalPreflightResult(
            proposal_id=proposal.metadata.id,
            state="invalid",
            operations=ops,
            findings=(
                PreflightFinding(
                    severity="error",
                    code="vault_root_failure",
                    operation_id=None,
                    target_path=None,
                    field_path=None,
                    message="Failed to securely open vault root directory",
                ),
            ),
        )

    try:
        # 2. Check for reserved target paths
        reserved_ops = False
        for op in proposal.patch_document.operations:
            if op.target_path == str(DEFAULT_OWNERSHIP_MANIFEST_PATH):
                reserved_ops = True
                break

        if reserved_ops:
            ops_list = []
            for op in proposal.patch_document.operations:
                op_findings = []
                if op.target_path == str(DEFAULT_OWNERSHIP_MANIFEST_PATH):
                    op_findings.append(
                        PreflightFinding(
                            severity="error",
                            code="reserved_authorization_target",
                            operation_id=op.id,
                            target_path=op.target_path,
                            field_path=None,
                            message="Cannot directly patch the generated ownership manifest",
                        )
                    )
                else:
                    op_findings.append(
                        PreflightFinding(
                            severity="error",
                            code="aborted",
                            operation_id=op.id,
                            target_path=op.target_path,
                            field_path=None,
                            message="Operation aborted due to invalid operation in proposal",
                        )
                    )
                ops_list.append(
                    OperationPreflightResult(
                        operation_id=op.id,
                        target_path=op.target_path,
                        state="invalid",
                        findings=tuple(op_findings),
                    )
                )
            return ProposalPreflightResult(
                proposal_id=proposal.metadata.id,
                state="invalid",
                operations=tuple(ops_list),
                findings=(),
            )

        # 3. Empty document
        if not proposal.patch_document.operations:
            return ProposalPreflightResult(
                proposal_id=proposal.metadata.id,
                state="valid",
                operations=(),
                findings=(),
            )

        # 4. Read canonical ownership manifest once
        manifest_bytes = None
        manifest_err_finding = None
        try:
            manifest_bytes = read_file_secure(
                str(DEFAULT_OWNERSHIP_MANIFEST_PATH),
                vault_root,
                dir_fd=root_fd,
                max_bytes=max_inspection_bytes,
            )
        except SecureIOError as e:
            if e.code == "open_failed":
                # missing manifest is invalid for non-empty proposal
                manifest_err_finding = PreflightFinding(
                    severity="error",
                    code="manifest_missing",
                    operation_id=None,
                    target_path=str(DEFAULT_OWNERSHIP_MANIFEST_PATH),
                    field_path=None,
                    message="Ownership manifest is missing or unreadable",
                )
            elif e.code == "target_too_large_for_inspection":
                manifest_err_finding = PreflightFinding(
                    severity="error",
                    code="manifest_too_large_for_inspection",
                    operation_id=None,
                    target_path=str(DEFAULT_OWNERSHIP_MANIFEST_PATH),
                    field_path=None,
                    message=e.message,
                )
            else:
                manifest_err_finding = PreflightFinding(
                    severity="error",
                    code="manifest_unsafe",
                    operation_id=None,
                    target_path=str(DEFAULT_OWNERSHIP_MANIFEST_PATH),
                    field_path=None,
                    message=f"Ownership manifest is unsafe or invalid: {e.message}",
                )

        ownership = None
        if manifest_bytes is not None:
            try:
                ownership = GeneratedOwnership.from_bytes(
                    manifest_bytes,
                    manifest_path=vault_root / DEFAULT_OWNERSHIP_MANIFEST_PATH,
                    vault_root=vault_root,
                )
            except ManifestError as e:
                manifest_err_finding = PreflightFinding(
                    severity="error",
                    code="manifest_malformed",
                    operation_id=None,
                    target_path=str(DEFAULT_OWNERSHIP_MANIFEST_PATH),
                    field_path=None,
                    message=f"Ownership manifest is malformed: {e}",
                )

        if manifest_err_finding:
            ops_list = []
            for op in proposal.patch_document.operations:
                ops_list.append(
                    OperationPreflightResult(
                        operation_id=op.id,
                        target_path=op.target_path,
                        state="invalid",
                        findings=(
                            PreflightFinding(
                                severity="error",
                                code="aborted",
                                operation_id=op.id,
                                target_path=op.target_path,
                                field_path=None,
                                message="Operation aborted due to manifest loading failure",
                            ),
                        ),
                    )
                )
            return ProposalPreflightResult(
                proposal_id=proposal.metadata.id,
                state="invalid",
                operations=tuple(ops_list),
                findings=(manifest_err_finding,),
            )

        assert ownership is not None

        # 5. Evaluate all operations independently
        op_results = []
        op_states = []

        for op in proposal.patch_document.operations:
            op_res = _evaluate_operation(op, vault_root, root_fd, ownership, max_inspection_bytes)
            op_results.append(op_res)
            op_states.append(op_res.state)

        return ProposalPreflightResult(
            proposal_id=proposal.metadata.id,
            state=_aggregate_state(op_states),
            operations=tuple(op_results),
            findings=(),
        )

    finally:
        os.close(root_fd)


def _check_target_status(
    target_path: str, vault_root: Path, root_fd: int | None
) -> tuple[bool, bool]:
    """Returns (exists, is_regular).
    Symlinks and directories return (True, False).
    """
    try:
        flags = os.O_RDONLY | os.O_NONBLOCK
        if hasattr(os, "O_NOFOLLOW"):
            flags |= getattr(os, "O_NOFOLLOW")
        if getattr(os, "open") in getattr(os, "supports_dir_fd", set()) and root_fd is not None:
            fd = os.open(target_path, flags, dir_fd=root_fd)
        else:
            fd = os.open(str(vault_root / target_path), flags)
    except OSError:
        return False, False

    try:
        st = os.fstat(fd)
        return True, stat.S_ISREG(st.st_mode)
    finally:
        os.close(fd)


def _evaluate_operation(
    op: PatchOperation,
    vault_root: Path,
    root_fd: int,
    ownership: GeneratedOwnership,
    max_bytes: int,
) -> OperationPreflightResult:
    target_path = op.target_path

    # Path safety
    norm_p = os.path.normpath(target_path)
    if os.path.isabs(norm_p) or norm_p.startswith("../") or norm_p == "..":
        return OperationPreflightResult(
            operation_id=op.id,
            target_path=target_path,
            state="invalid",
            findings=(
                PreflightFinding(
                    severity="error",
                    code="unsafe_path",
                    operation_id=op.id,
                    target_path=target_path,
                    field_path=None,
                    message="Target path is unsafe",
                ),
            ),
        )

    if op.op == "release_generated_ownership":
        try:
            os.stat(norm_p, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError as error:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="invalid",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="target_inspection_failed",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message=f"Failed to inspect ownership target: {error}",
                    ),
                ),
            )
        else:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="stale",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="target_restored",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Ownership target is present; release is no longer safe",
                    ),
                ),
            )

        entry = ownership.entries.get(norm_p)
        if entry is None:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="stale",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="ownership_entry_missing",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Ownership entry has already been released or changed",
                    ),
                ),
            )

        expected_entry = (
            f"sha256:{entry.content_hash}",
            entry.generator_id,
            entry.generator_version,
            entry.created_at,
            entry.updated_at,
        )
        reviewed_entry = (
            getattr(op, "expected_content_hash", ""),
            getattr(op, "expected_generator_id", ""),
            getattr(op, "expected_generator_version", ""),
            getattr(op, "expected_created_at", ""),
            getattr(op, "expected_updated_at", ""),
        )
        if reviewed_entry != expected_entry:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="stale",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="ownership_entry_changed",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Ownership entry no longer matches the reviewed record",
                    ),
                ),
            )

        return OperationPreflightResult(
            operation_id=op.id,
            target_path=target_path,
            state="valid",
            findings=(),
        )

    if op.op == "create_generated_file" or op.op == "create_file":
        if target_path in ownership.entries:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="invalid",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="ownership_conflict",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Cannot create target that already has an ownership entry",
                    ),
                ),
            )

        # Check existing parent safety
        parent = Path(norm_p).parent
        if str(parent) != ".":
            p_exists, p_reg = _check_target_status(str(parent), vault_root, root_fd)
            if not p_exists and not str(parent) == ".":
                pass # Parent might not exist, which is fine normally, but wait, criteria says "missing parent is invalid"
                # Actually, check parent properly: if parent does not exist, or parent is a symlink, invalid

                # Check entire parent chain simply
                curr = vault_root
                for part in parent.parts:
                    curr = curr / part
                    if curr.is_symlink():
                        return OperationPreflightResult(
                            operation_id=op.id,
                            target_path=target_path,
                            state="invalid",
                            findings=(
                                PreflightFinding(
                                    severity="error",
                                    code="unsafe_parent",
                                    operation_id=op.id,
                                    target_path=target_path,
                                    field_path=None,
                                    message="Parent chain contains a symlink",
                                ),
                            ),
                        )
                    if not curr.exists():
                        missing_relative = curr.relative_to(vault_root).as_posix()
                        if (
                            op.op == "create_generated_file"
                            and missing_relative not in {"wiki", "flashcards"}
                            and is_emergent_generated_parent(parent.as_posix())
                        ):
                            # An approved generated wiki create may materialize
                            # the remaining bounded parent chain under an
                            # already-existing canonical wiki root.
                            break
                        return OperationPreflightResult(
                            operation_id=op.id,
                            target_path=target_path,
                            state="invalid",
                            findings=(
                                PreflightFinding(
                                    severity="error",
                                    code="missing_parent",
                                    operation_id=op.id,
                                    target_path=target_path,
                                    field_path=None,
                                    message="Missing parent directory",
                                ),
                            ),
                        )
                    if not curr.is_dir():
                        return OperationPreflightResult(
                            operation_id=op.id,
                            target_path=target_path,
                            state="invalid",
                            findings=(
                                PreflightFinding(
                                    severity="error",
                                    code="parent_not_directory",
                                    operation_id=op.id,
                                    target_path=target_path,
                                    field_path=None,
                                    message="Parent is not a directory",
                                ),
                            ),
                        )

        exists, is_reg = _check_target_status(norm_p, vault_root, root_fd)
        if not exists:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="valid",
                findings=(),
            )
        if is_reg:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="stale",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="target_exists",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Target regular file already exists",
                    ),
                ),
            )
        return OperationPreflightResult(
            operation_id=op.id,
            target_path=target_path,
            state="invalid",
            findings=(
                PreflightFinding(
                    severity="error",
                    code="invalid_target_type",
                    operation_id=op.id,
                    target_path=target_path,
                    field_path=None,
                    message="Target exists and is not a regular file",
                ),
            ),
        )

    if op.op == "replace_generated_file":
        exists, is_reg = _check_target_status(norm_p, vault_root, root_fd)
        if not exists:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="stale",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="missing_target",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Target file is missing",
                    ),
                ),
            )
        if not is_reg:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="invalid",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="invalid_target_type",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Target exists and is not a regular file",
                    ),
                ),
            )

        try:
            current_digest = hash_file_secure(norm_p, vault_root, root_fd, max_bytes=None)
        except SecureIOError as e:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="invalid",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code=e.code,
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message=f"Failed to read target: {e.message}",
                    ),
                ),
            )

        entry = ownership.entries.get(norm_p)
        if not entry:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="invalid",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="missing_ownership",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Missing ownership entry for generated file",
                    ),
                ),
            )

        expected_generator_id = getattr(op, "expected_generator_id", None)
        if entry.generator_id != expected_generator_id:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="invalid",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="generator_mismatch",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Generator identity mismatch",
                    ),
                ),
            )

        if entry.content_hash != current_digest:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="invalid",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="unauthorized_modification",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Manifest content hash does not match current raw digest",
                    ),
                ),
            )

        patch_base_hash = getattr(op, "base_hash", "")
        expected_base_hash = f"sha256:{current_digest}"
        if patch_base_hash != expected_base_hash:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="stale",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="stale_base_hash",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Patch base_hash does not match target file hash",
                    ),
                ),
            )

        return OperationPreflightResult(
            operation_id=op.id,
            target_path=target_path,
            state="valid",
            findings=(),
        )

    if op.op == "patch_human_file" or op.op == "replace_managed_block":
        if norm_p in ownership.entries:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="invalid",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="ownership_conflict",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Cannot modify file claimed by generated ownership",
                    ),
                ),
            )

        try:
            content_bytes = read_file_secure(norm_p, vault_root, root_fd, max_bytes)
        except SecureIOError as e:
            state: PreflightState = "invalid"
            if e.code == "open_failed":
                state = "stale"
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state=state,
                findings=(
                    PreflightFinding(
                        severity="error",
                        code=e.code,
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message=f"Failed to read target: {e.message}",
                    ),
                ),
            )

        try:
            content_str = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="invalid",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="invalid_utf8",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Target file is not strict UTF-8",
                    ),
                ),
            )

        current_digest = hashlib.sha256(content_bytes).hexdigest()
        patch_base_hash = getattr(op, "base_hash", "")
        expected_base_hash = f"sha256:{current_digest}"

        if patch_base_hash != expected_base_hash:
            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="stale",
                findings=(
                    PreflightFinding(
                        severity="error",
                        code="stale_base_hash",
                        operation_id=op.id,
                        target_path=target_path,
                        field_path=None,
                        message="Patch base_hash does not match target file hash",
                    ),
                ),
            )

        if op.op == "patch_human_file":
            if target_path.endswith(".md"):
                parsed = parse_markdown_note(vault_root / norm_p, content=content_str)
                if any(f.severity == "error" for f in parsed.findings):
                    return OperationPreflightResult(
                        operation_id=op.id,
                        target_path=target_path,
                        state="invalid",
                        findings=(
                            PreflightFinding(
                                severity="error",
                                code="malformed_markdown",
                                operation_id=op.id,
                                target_path=target_path,
                                field_path=None,
                                message="Target Markdown structure is invalid",
                            ),
                        ),
                    )
                if parsed.managed_blocks:
                    return OperationPreflightResult(
                        operation_id=op.id,
                        target_path=target_path,
                        state="invalid",
                        findings=(
                            PreflightFinding(
                                severity="error",
                                code="managed_blocks_present",
                                operation_id=op.id,
                                target_path=target_path,
                                field_path=None,
                                message="Target contains managed blocks, cannot use patch_human_file",
                            ),
                        ),
                    )

            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="valid",
                findings=(),
            )

        if op.op == "replace_managed_block":
            if not target_path.endswith(".md"):
                return OperationPreflightResult(
                    operation_id=op.id,
                    target_path=target_path,
                    state="invalid",
                    findings=(
                        PreflightFinding(
                            severity="error",
                            code="invalid_target_type",
                            operation_id=op.id,
                            target_path=target_path,
                            field_path=None,
                            message="Target must be a Markdown file",
                        ),
                    ),
                )

            parsed = parse_markdown_note(vault_root / norm_p, content=content_str)
            if any(f.severity == "error" for f in parsed.findings):
                return OperationPreflightResult(
                    operation_id=op.id,
                    target_path=target_path,
                    state="invalid",
                    findings=(
                        PreflightFinding(
                            severity="error",
                            code="malformed_markdown",
                            operation_id=op.id,
                            target_path=target_path,
                            field_path=None,
                            message="Target Markdown structure is invalid",
                        ),
                    ),
                )

            block_name = getattr(op, "block_name", "")
            matches = [b for b in parsed.managed_blocks if b.name == block_name]
            if len(matches) != 1:
                return OperationPreflightResult(
                    operation_id=op.id,
                    target_path=target_path,
                    state="invalid",
                    findings=(
                        PreflightFinding(
                            severity="error",
                            code="managed_block_not_found" if not matches else "ambiguous_managed_block",
                            operation_id=op.id,
                            target_path=target_path,
                            field_path=None,
                            message=f"Managed block '{block_name}' must exist exactly once",
                        ),
                    ),
                )

            target_block = matches[0]
            new_content = getattr(op, "new_content", "")

            if "<!-- lifeos:managed" in new_content:
                return OperationPreflightResult(
                    operation_id=op.id,
                    target_path=target_path,
                    state="invalid",
                    findings=(
                        PreflightFinding(
                            severity="error",
                            code="marker_injection",
                            operation_id=op.id,
                            target_path=target_path,
                            field_path=None,
                            message="Replacement content contains managed marker injection",
                        ),
                    ),
                )

            # Construct candidate in memory using boundaries
            # Preserve opening marker, closing marker, existing surrounding line endings.

            lines = content_str.split("\n")

            # The target_block gives us start_line and end_line (1-indexed).
            # The body is between start_line and end_line exclusively.

            # We want to replace lines[target_block.start_line : target_block.end_line - 1]
            # with the new content (split into lines).
            # If new_content is empty, we just insert no lines.

            # However, parser lines are 1-indexed.
            start_idx = target_block.start_line
            end_idx = target_block.end_line - 1

            new_lines = new_content.split("\n") if new_content else []
            candidate_lines = lines[:start_idx] + new_lines + lines[end_idx:]
            candidate_str = "\n".join(candidate_lines)
            candidate_bytes = candidate_str.encode("utf-8")

            if len(candidate_bytes) > max_bytes:
                return OperationPreflightResult(
                    operation_id=op.id,
                    target_path=target_path,
                    state="invalid",
                    findings=(
                        PreflightFinding(
                            severity="error",
                            code="candidate_too_large_for_inspection",
                            operation_id=op.id,
                            target_path=target_path,
                            field_path=None,
                            message="Candidate replacement exceeds max inspection bytes",
                        ),
                    ),
                )

            candidate_parsed = parse_markdown_note(vault_root / norm_p, content=candidate_str)
            if any(f.severity == "error" for f in candidate_parsed.findings):
                return OperationPreflightResult(
                    operation_id=op.id,
                    target_path=target_path,
                    state="invalid",
                    findings=(
                        PreflightFinding(
                            severity="error",
                            code="malformed_candidate",
                            operation_id=op.id,
                            target_path=target_path,
                            field_path=None,
                            message="Candidate Markdown structure is invalid",
                        ),
                    ),
                )

            candidate_matches = [b for b in candidate_parsed.managed_blocks if b.name == block_name]
            if len(candidate_matches) != 1:
                return OperationPreflightResult(
                    operation_id=op.id,
                    target_path=target_path,
                    state="invalid",
                    findings=(
                        PreflightFinding(
                            severity="error",
                            code="candidate_block_error",
                            operation_id=op.id,
                            target_path=target_path,
                            field_path=None,
                            message="Candidate must retain the managed block exactly once",
                        ),
                    ),
                )

            return OperationPreflightResult(
                operation_id=op.id,
                target_path=target_path,
                state="valid",
                findings=(),
            )

    return OperationPreflightResult(
        operation_id=op.id,
        target_path=target_path,
        state="invalid",
        findings=(
            PreflightFinding(
                severity="error",
                code="unsupported_operation",
                operation_id=op.id,
                target_path=target_path,
                field_path=None,
                message="Operation type not supported in preflight",
            ),
        ),
    )
