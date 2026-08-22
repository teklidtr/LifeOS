from pathlib import Path

import pytest

from lifeos.facade.errors import ToolExecutionError
from lifeos.facade.models import ToolEffect
from lifeos.facade.registry_tools import (
    REGISTRY_REFRESH_DESCRIPTOR,
    refresh_registry,
)
from lifeos.registry import Registry
from lifeos.scanner import ScannerError


def test_refresh_registers_move_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    source = vault / "study" / "example.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Example\n", encoding="utf-8")
    registry = Registry(runtime / "registry.db")
    monkeypatch.setattr(
        "lifeos.facade.registry_tools.register_proposals_scan",
        lambda _registry, *, vault_root: None,
    )

    first = refresh_registry(vault_root=vault, registry=registry)
    assert first.new == ("study/example.md",)

    target = vault / "study" / "ehliyet" / "example.md"
    target.parent.mkdir()
    source.rename(target)

    moved = refresh_registry(vault_root=vault, registry=registry)
    assert moved.new == ("study/ehliyet/example.md",)
    assert moved.deleted == ("study/example.md",)

    repeated = refresh_registry(vault_root=vault, registry=registry)
    assert repeated.new == ()
    assert repeated.modified == ()
    assert repeated.deleted == ()
    assert repeated.unchanged == ("study/ehliyet/example.md",)


def test_refresh_descriptor_marks_rebuildable_write() -> None:
    assert REGISTRY_REFRESH_DESCRIPTOR.effect is ToolEffect.DERIVED_WRITE


def test_refresh_maps_scanner_failure_to_facade_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "lifeos.facade.registry_tools.scan_vault",
        lambda _root: (_ for _ in ()).throw(ScannerError("private path")),
    )

    with pytest.raises(ToolExecutionError, match="Could not refresh"):
        refresh_registry(
            vault_root=tmp_path / "vault",
            registry=Registry(tmp_path / "runtime" / "registry.db"),
        )
