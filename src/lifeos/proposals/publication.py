"""Secure publication of the canonical three-document proposal layout."""

from __future__ import annotations

import ctypes
import errno
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lifeos._atomic_write import AtomicWriteError, atomic_write_file_secure
from lifeos._secure_io import SecureIOError, open_directory_secure

ProposalPublicationErrorCode = Literal[
    "proposal_exists",
    "unsafe_proposal_id",
    "unsafe_proposals_root",
    "proposal_publish_failed",
]

_DOCUMENT_NAMES = ("proposal.md", "patches.json", "review.json")
_STAGING_PREFIX = ".lifeos-proposal-stage-"
FileIdentity = tuple[int, int]
OwnedFile = tuple[str, FileIdentity]


@dataclass(frozen=True, slots=True)
class ProposalDocuments:
    """Exact canonical bytes prepared by a proposal-producing feature."""

    proposal_markdown: bytes
    patches_json: bytes
    review_json: bytes


class ProposalPublicationError(RuntimeError):
    """Filesystem publication failure for a prepared proposal document set."""

    def __init__(self, code: ProposalPublicationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def publish_proposal_documents(
    *,
    vault_root: Path,
    proposal_id: str,
    documents: ProposalDocuments,
) -> None:
    """Publish one prepared draft without taking ownership of feature semantics.

    The caller owns validation, source/target revalidation, serialization, and review-snapshot
    construction. This function owns only the canonical ``proposals/<id>/`` publication step.
    Prepared bytes are written to a private staging directory, then the completed directory is
    moved into its stable proposal ID with an operating-system no-replace rename. Cleanup is
    descriptor-relative and limited to entries whose identity still belongs to this attempt.
    """
    _validate_proposal_id(proposal_id)

    vault_fd = proposals_fd = proposal_fd = -1
    publication_complete = False
    directory_name: str | None = None
    owned_files: list[OwnedFile] = []
    created_identity: FileIdentity | None = None
    try:
        vault_fd, proposals_fd = _open_proposals_root(vault_root)
        _raise_if_proposal_exists(proposals_fd, proposal_id)
        directory_name, proposal_fd, created_identity = _create_staging_directory(proposals_fd)

        for filename, content in zip(
            _DOCUMENT_NAMES,
            (documents.proposal_markdown, documents.patches_json, documents.review_json),
            strict=True,
        ):
            _require_publication_boundaries(
                vault_fd=vault_fd,
                proposals_fd=proposals_fd,
                proposal_fd=proposal_fd,
                directory_name=directory_name,
            )
            published_identity: FileIdentity | None = None

            def remember_identity(identity: FileIdentity) -> None:
                nonlocal published_identity
                published_identity = identity

            atomic_write_file_secure(
                proposal_fd,
                filename,
                content,
                published_identity=remember_identity,
            )
            if published_identity is None:
                raise ProposalPublicationError(
                    "proposal_publish_failed",
                    f"Published file identity was not recorded: {filename}",
                )
            owned_files.append((filename, published_identity))

        _require_publication_boundaries(
            vault_fd=vault_fd,
            proposals_fd=proposals_fd,
            proposal_fd=proposal_fd,
            directory_name=directory_name,
        )
        try:
            _rename_directory_noreplace(
                parent_fd=proposals_fd,
                source_name=directory_name,
                target_name=proposal_id,
            )
        except FileExistsError as exc:
            raise ProposalPublicationError(
                "proposal_exists",
                f"Proposal directory already exists: proposals/{proposal_id}",
            ) from exc
        directory_name = proposal_id

        _require_publication_boundaries(
            vault_fd=vault_fd,
            proposals_fd=proposals_fd,
            proposal_fd=proposal_fd,
            directory_name=directory_name,
        )
        publication_complete = True
    except ProposalPublicationError:
        raise
    except (AtomicWriteError, OSError) as exc:
        raise ProposalPublicationError("proposal_publish_failed", str(exc)) from exc
    finally:
        if not publication_complete and directory_name is not None:
            _cleanup_owned_attempt(
                proposals_fd=proposals_fd,
                proposal_fd=proposal_fd,
                directory_name=directory_name,
                owned_files=owned_files,
                created_identity=created_identity,
            )
        if proposal_fd >= 0:
            os.close(proposal_fd)
        if proposals_fd >= 0:
            os.close(proposals_fd)
        if vault_fd >= 0:
            os.close(vault_fd)


def _validate_proposal_id(proposal_id: str) -> None:
    if (
        type(proposal_id) is not str
        or not proposal_id
        or proposal_id in {".", ".."}
        or "/" in proposal_id
        or "\\" in proposal_id
        or "\x00" in proposal_id
        or Path(proposal_id).is_absolute()
    ):
        raise ProposalPublicationError(
            "unsafe_proposal_id",
            "Proposal id is not safe for publication.",
        )


def _open_proposals_root(vault_root: Path) -> tuple[int, int]:
    vault_fd = -1
    try:
        try:
            vault_fd = open_directory_secure(vault_root)
        except SecureIOError as exc:
            raise ProposalPublicationError(
                "unsafe_proposals_root",
                "Proposal root is not a safe directory.",
            ) from exc

        try:
            os.mkdir("proposals", mode=0o755, dir_fd=vault_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise ProposalPublicationError("proposal_publish_failed", str(exc)) from exc

        try:
            proposals_fd = open_directory_secure(Path("proposals"), dir_fd=vault_fd)
        except SecureIOError as exc:
            raise ProposalPublicationError(
                "unsafe_proposals_root",
                "Proposal root is not a safe directory.",
            ) from exc
        if not _directory_entry_matches(vault_fd, "proposals", proposals_fd):
            os.close(proposals_fd)
            raise ProposalPublicationError(
                "unsafe_proposals_root",
                "Proposal root changed during publication.",
            )
        return vault_fd, proposals_fd
    except Exception:
        if vault_fd >= 0:
            os.close(vault_fd)
        raise


def _raise_if_proposal_exists(proposals_fd: int, proposal_id: str) -> None:
    try:
        os.stat(proposal_id, dir_fd=proposals_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ProposalPublicationError("proposal_publish_failed", str(exc)) from exc
    raise ProposalPublicationError(
        "proposal_exists",
        f"Proposal directory already exists: proposals/{proposal_id}",
    )


def _create_staging_directory(proposals_fd: int) -> tuple[str, int, FileIdentity]:
    """Create an unguessable private staging directory for one publication attempt."""
    for _ in range(16):
        directory_name = f"{_STAGING_PREFIX}{secrets.token_hex(16)}"
        try:
            os.mkdir(directory_name, mode=0o700, dir_fd=proposals_fd)
        except FileExistsError:
            continue
        try:
            proposal_fd = open_directory_secure(Path(directory_name), dir_fd=proposals_fd)
        except SecureIOError as exc:
            raise ProposalPublicationError("proposal_publish_failed", str(exc)) from exc
        created_identity = _fd_identity(proposal_fd)
        if not _directory_entry_matches(proposals_fd, directory_name, proposal_fd):
            os.close(proposal_fd)
            raise ProposalPublicationError(
                "proposal_publish_failed",
                "Proposal staging directory changed during publication.",
            )
        return directory_name, proposal_fd, created_identity
    raise ProposalPublicationError(
        "proposal_publish_failed",
        "Could not allocate a unique proposal staging directory.",
    )


def _rename_directory_noreplace(
    *,
    parent_fd: int,
    source_name: str,
    target_name: str,
) -> None:
    """Atomically publish a staged directory without replacing an existing target."""
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    target = os.fsencode(target_name)

    if sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(errno.ENOTSUP, "renameat2 is unavailable")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(parent_fd, source, parent_fd, target, 1)
    elif sys.platform == "darwin":
        renameatx_np = getattr(libc, "renameatx_np", None)
        if renameatx_np is None:
            raise OSError(errno.ENOTSUP, "renameatx_np is unavailable")
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        result = renameatx_np(parent_fd, source, parent_fd, target, 0x00000004)
    else:
        raise OSError(errno.ENOTSUP, "exclusive directory rename is unsupported on this platform")

    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), target_name)


def _require_publication_boundaries(
    *,
    vault_fd: int,
    proposals_fd: int,
    proposal_fd: int,
    directory_name: str,
) -> None:
    if not _directory_entry_matches(vault_fd, "proposals", proposals_fd):
        raise ProposalPublicationError(
            "unsafe_proposals_root",
            "Proposal root changed during publication.",
        )
    if not _directory_entry_matches(proposals_fd, directory_name, proposal_fd):
        raise ProposalPublicationError(
            "proposal_publish_failed",
            "Proposal directory changed during publication.",
        )


def _fd_identity(fd: int) -> FileIdentity:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def _directory_entry_matches(parent_fd: int, name: str, child_fd: int) -> bool:
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        opened = os.fstat(child_fd)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (
        opened.st_dev,
        opened.st_ino,
    )


def _file_entry_matches(parent_fd: int, name: str, identity: FileIdentity) -> bool:
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity


def _cleanup_owned_attempt(
    *,
    proposals_fd: int,
    proposal_fd: int,
    directory_name: str,
    owned_files: list[OwnedFile],
    created_identity: FileIdentity | None,
) -> None:
    if proposal_fd < 0 or created_identity is None:
        return
    if _fd_identity(proposal_fd) != created_identity:
        return

    for filename, identity in reversed(owned_files):
        if not _file_entry_matches(proposal_fd, filename, identity):
            continue
        try:
            os.unlink(filename, dir_fd=proposal_fd)
        except OSError:
            pass

    if proposals_fd < 0 or not _directory_entry_matches(
        proposals_fd,
        directory_name,
        proposal_fd,
    ):
        return
    try:
        os.rmdir(directory_name, dir_fd=proposals_fd)
    except OSError:
        pass
