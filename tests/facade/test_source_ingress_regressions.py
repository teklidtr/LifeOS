from __future__ import annotations

from pathlib import Path

import pytest

from lifeos.captures.artifact import CaptureArtifactService
from lifeos.facade import (
    SourceImportRequest,
    ToolNotFoundError,
    ToolValidationError,
    import_source,
)


def test_rejected_ingress_never_creates_an_empty_capture(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    captures = CaptureArtifactService(vault_root=vault, runtime_dir=runtime)

    missing = tmp_path / "missing.txt"
    with pytest.raises(ToolNotFoundError):
        import_source(
            vault_root=vault,
            runtime_dir=runtime,
            request=SourceImportRequest(str(missing)),
        )
    assert captures.list() == ()

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ToolValidationError):
        import_source(
            vault_root=vault,
            runtime_dir=runtime,
            request=SourceImportRequest(str(directory)),
        )
    assert captures.list() == ()

    target = tmp_path / "target.txt"
    target.write_text("target")
    symlink = tmp_path / "source-link.txt"
    symlink.symlink_to(target)
    with pytest.raises(ToolNotFoundError):
        import_source(
            vault_root=vault,
            runtime_dir=runtime,
            request=SourceImportRequest(str(symlink)),
        )
    assert captures.list() == ()
