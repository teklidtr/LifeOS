from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import pytest

from lifeos.context import ContextSearchError, lexical_search
from lifeos.exports import ExportError, build_export
from lifeos.facade.errors import ToolValidationError
from lifeos.facade.read_only import ReadMarkdownRequest, read_markdown
from lifeos.graph import GraphError, build_graph_document
from lifeos.observation import ObservationError, load_observations
from lifeos.planning import PlanningError, load_plan_actions
from lifeos.study import StudyError, load_flashcards
from lifeos.vault import VaultAccessError, iter_vault_markdown, read_vault_markdown


def test_file_symlink_to_external_markdown_is_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    (vault / "link.md").symlink_to(outside)

    with pytest.raises(VaultAccessError) as exc_info:
        iter_vault_markdown(vault)

    assert exc_info.value.code == "unsafe-symlink"
    assert exc_info.value.relative_path == "link.md"


def test_directory_symlink_to_external_directory_is_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    (vault / "wiki").symlink_to(outside, target_is_directory=True)

    with pytest.raises(VaultAccessError) as exc_info:
        iter_vault_markdown(vault)

    assert exc_info.value.code == "unsafe-symlink"
    assert exc_info.value.relative_path == "wiki"


def test_file_swapped_to_symlink_between_listing_and_open_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    target = vault / "note.md"
    target.write_text("safe", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    original_open = os.open
    swapped = False

    def swap_before_open(
        path: str | bytes | int | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "note.md" and dir_fd is not None and not swapped:
            target.unlink()
            target.symlink_to(outside)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_before_open)

    with pytest.raises(VaultAccessError) as exc_info:
        iter_vault_markdown(vault)

    assert exc_info.value.code == "unsafe-symlink"


def test_nested_markdown_is_read_in_deterministic_order(tmp_path: Path) -> None:
    (tmp_path / "z").mkdir()
    (tmp_path / "a" / "nested").mkdir(parents=True)
    (tmp_path / "z" / "last.md").write_text("last", encoding="utf-8")
    (tmp_path / "a" / "first.md").write_text("first", encoding="utf-8")
    (tmp_path / "a" / "nested" / "middle.md").write_text("middle", encoding="utf-8")

    files = iter_vault_markdown(tmp_path)

    assert [item.relative_path for item in files] == [
        "a/first.md",
        "a/nested/middle.md",
        "z/last.md",
    ]
    assert [item.content for item in files] == ["first", "middle", "last"]


def test_read_closes_descriptors_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "note.md").write_text("body", encoding="utf-8")
    original_close = os.close
    closed: list[int] = []

    def recording_close(fd: int) -> None:
        closed.append(fd)
        original_close(fd)

    monkeypatch.setattr(os, "close", recording_close)
    source = read_vault_markdown(tmp_path, "dir/note.md")

    assert source.content == "body"
    assert len(closed) == len(set(closed))
    assert len(closed) == 3


@pytest.mark.parametrize(
    ("root_name", "consumer", "error_type"),
    [
        ("wiki", lambda vault, runtime: lexical_search(vault_root=vault, query="secret"), ContextSearchError),
        ("flashcards", lambda vault, runtime: load_flashcards(vault), StudyError),
        ("plans", lambda vault, runtime: load_plan_actions(vault), PlanningError),
        ("journal", lambda vault, runtime: load_observations(vault), ObservationError),
        (
            "wiki",
            lambda vault, runtime: build_graph_document(vault_root=vault, view_name="knowledge"),
            GraphError,
        ),
        (
            "wiki",
            lambda vault, runtime: build_export(
                vault_root=vault,
                runtime_dir=runtime,
                kind="public-wiki",
            ),
            ExportError,
        ),
    ],
)
def test_domain_consumers_reject_unsafe_sources(
    tmp_path: Path,
    root_name: str,
    consumer: Callable[[Path, Path], object],
    error_type: type[Exception],
) -> None:
    vault = tmp_path / "vault"
    root = vault / root_name
    root.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    (root / "unsafe.md").symlink_to(outside)

    with pytest.raises(error_type, match="Unsafe symlink"):
        consumer(vault, tmp_path / "runtime")


def test_facade_rejects_concurrent_symlink_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    target = vault / "note.md"
    target.write_text("safe", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    original_open = os.open
    swapped = False

    def swap_before_open(
        path: str | bytes | int | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "note.md" and dir_fd is not None and not swapped:
            target.unlink()
            target.symlink_to(outside)
            swapped = True
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_before_open)

    with pytest.raises(ToolValidationError, match="Unsafe vault path"):
        read_markdown(vault_root=vault, request=ReadMarkdownRequest(vault_path="note.md"))
