from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lifeos.proposals import application
from lifeos.proposals.recovery_store import acquire_pinned_recovery_store


def test_application_authority_check_rejects_vault_path_swap(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    parked = tmp_path / "vault-pinned"

    with acquire_pinned_recovery_store(
        runtime_dir=runtime,
        authority_root=vault,
    ) as store:
        vault.rename(parked)
        vault.mkdir()

        with pytest.raises(application.ApplicationError) as exc_info:
            application._require_current_recovery_authority(
                recovery_store=store,
                outcome=MagicMock(),
            )

    assert exc_info.value.code is application.ApplicationErrorCode.RECOVERY_REQUIRED


def test_application_directory_chain_stays_on_pinned_vault_inode_after_swap(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    original_wiki = vault / "wiki"
    original_wiki.mkdir(parents=True)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    parked = tmp_path / "vault-pinned"

    with acquire_pinned_recovery_store(
        runtime_dir=runtime,
        authority_root=vault,
    ) as store:
        root_fd = store.open_authority_root()
        try:
            vault.rename(parked)
            replacement_wiki = vault / "wiki"
            replacement_wiki.mkdir(parents=True)

            wiki_fd = application._open_directory_chain(root_fd, "wiki")
            try:
                opened = os.fstat(wiki_fd)
            finally:
                os.close(wiki_fd)

            original = os.stat(parked / "wiki", follow_symlinks=False)
            replacement = os.stat(replacement_wiki, follow_symlinks=False)
            assert (opened.st_dev, opened.st_ino) == (original.st_dev, original.st_ino)
            assert (opened.st_dev, opened.st_ino) != (replacement.st_dev, replacement.st_ino)
        finally:
            os.close(root_fd)


def test_target_install_rechecks_authority_before_each_publish() -> None:
    prepared = MagicMock()
    prepared.original_identity = None
    prepared.target_name = "note.md"
    prepared.index = 0
    prepared.staging = MagicMock()
    require_authority = MagicMock(side_effect=RuntimeError("authority changed"))

    with patch.object(application, "publish_creation") as publish:
        with pytest.raises(RuntimeError, match="authority changed"):
            application._install_prepared_targets(
                prepared_ops=[prepared],
                outcome=MagicMock(),
                durability="confirmed",
                update_op_state=MagicMock(),
                require_authority=require_authority,
            )

    require_authority.assert_called_once_with()
    publish.assert_not_called()


def test_generated_parent_creation_checks_authority_before_mkdir(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    root_fd = os.open(vault, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    operation = MagicMock(op="create_generated_file")
    require_authority = MagicMock(side_effect=RuntimeError("authority changed"))

    try:
        with patch.object(application, "is_emergent_generated_parent", return_value=True):
            with pytest.raises(RuntimeError, match="authority changed"):
                application._open_or_create_target_parent(
                    vault_root=vault,
                    root_fd=root_fd,
                    parent_relative="wiki/generated/concepts",
                    operation=operation,
                    created_parent_paths=[],
                    require_authority=require_authority,
                )
    finally:
        os.close(root_fd)

    assert not (vault / "wiki" / "generated").exists()


def test_failed_generated_parent_cleanup_uses_pinned_root_after_vault_swap(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    original_generated = vault / "wiki" / "generated"
    original_generated.mkdir(parents=True)
    root_fd = os.open(vault, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    parked = tmp_path / "vault-pinned"

    try:
        vault.rename(parked)
        replacement_generated = vault / "wiki" / "generated"
        replacement_generated.mkdir(parents=True)

        application._cleanup_created_parent_paths(
            root_fd=root_fd,
            created_parent_paths=["wiki/generated"],
        )

        assert not (parked / "wiki" / "generated").exists()
        assert replacement_generated.is_dir()
    finally:
        os.close(root_fd)
