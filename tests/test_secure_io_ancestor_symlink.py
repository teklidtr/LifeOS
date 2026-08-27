import os
from pathlib import Path

import pytest

from lifeos._secure_io import SecureIOError, open_directory_secure


def test_open_directory_secure_rejects_symlinked_ancestor(tmp_path: Path) -> None:
    if os.open not in getattr(os, "supports_dir_fd", set()) or not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("secure ancestor walking requires POSIX dir_fd and O_NOFOLLOW support")

    real_vault = tmp_path / "real-vault"
    (real_vault / "proposals").mkdir(parents=True)
    aliased_vault = tmp_path / "aliased-vault"
    aliased_vault.symlink_to(real_vault, target_is_directory=True)

    with pytest.raises(SecureIOError) as exc_info:
        open_directory_secure(aliased_vault / "proposals")

    assert exc_info.value.code == "dir_open_failed"
