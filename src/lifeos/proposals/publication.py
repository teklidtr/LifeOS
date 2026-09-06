"""Secure publication of the canonical three-document proposal layout."""

from __future__ import annotations

import os
import stat
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
    construction. This function owns only the stable ``proposals/<id>/`` directory and the exact
    three document writes. The writes are descriptor-relative and cleanup is limited to entries
    that still belong to this failed publication attempt.
    """
    _validate_proposal_id(proposal_id)

    vault_fd = proposals_fd = proposal_fd = -1
    proposal_created = publication_complete = False
    owned_files: list[OwnedFile] = []
    created_identity: FileIdentity | None = None
    try:
        vault_fd, proposals_fd = _open_proposals_root(vault_root)
        try:
            os.mkdir(proposal_id, mode=0o755, dir_fd=proposals_fd)
            proposal_created = True
        except FileExistsError as exc:
            raise ProposalPublicationError(
                "proposal_exists",
                f"Proposal directory already exists: proposals/{proposal_id}",
            ) from exc

        try:
            created_identity = _directory_entry_identity(proposals_fd, proposal_id)
            proposal_fd = open_directory_secure(Path(proposal_id), dir_fd=proposals_fd)
        except SecureIOError as exc:
            raise ProposalPublicationError("proposal_publish_failed", str(exc)) from exc
        if _fd_identity(proposal_fd) != created_identity:
            raise ProposalPublicationError(
                "proposal_publish_failed",
                "Proposal directory changed during publication.",
            )

        for filename, content in zip(
            _DOCUMENT_NAMES,
            (documents.proposal_markdown, documents.patches_json, documents.review_json),
            strict=True,
        ):
            _require_publication_boundaries(
                vault_fd=vault_fd,
                proposals_fd=proposals_fd,
                proposal_fd=proposal_fd,
                proposal_id=proposal_id,
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
            proposal_id=proposal_id,
        )
        publication_complete = True
    except ProposalPublicationError:
        raise
    except (AtomicWriteError, OSError) as exc:
        raise ProposalPublicationError("proposal_publish_failed", str(exc)) from exc
    finally:
        if proposal_created and not publication_complete:
            _cleanup_owned_attempt(
                proposals_fd=proposals_fd,
                proposal_fd=proposal_fd,
                proposal_id=proposal_id,
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


def _require_publication_boundaries(
    *,
    vault_fd: int,
    proposals_fd: int,
    proposal_fd: int,
    proposal_id: str,
) -> None:
    if not _directory_entry_matches(vault_fd, "proposals", proposals_fd):
        raise ProposalPublicationError(
            "unsafe_proposals_root",
            "Proposal root changed during publication.",
        )
    if not _directory_entry_matches(proposals_fd, proposal_id, proposal_fd):
        raise ProposalPublicationError(
            "proposal_publish_failed",
            "Proposal directory changed during publication.",
        )


def _directory_entry_identity(parent_fd: int, name: str) -> FileIdentity:
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise ProposalPublicationError("proposal_publish_failed", str(exc)) from exc
    if not stat.S_ISDIR(info.st_mode):
        raise ProposalPublicationError(
            "proposal_publish_failed",
            "Proposal path is not a directory.",
        )
    return info.st_dev, info.st_ino


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
    proposal_id: str,
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

    if proposals_fd < 0 or not _directory_entry_matches(proposals_fd, proposal_id, proposal_fd):
        return
    try:
        os.rmdir(proposal_id, dir_fd=proposals_fd)
    except OSError:
        pass
