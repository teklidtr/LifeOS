from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lifeos.facade.errors import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
)
from lifeos.facade.models import ToolEffect
from lifeos.facade.read_only import (
    READ_MARKDOWN_DESCRIPTOR,
    WIKI_SEARCH_DESCRIPTOR,
    VAULT_CONTEXT_DESCRIPTOR,
    ReadMarkdownRequest,
    ReadMarkdownResult,
    WikiSearchRequest,
    VaultContextRequest,
    get_vault_context,
    read_markdown,
    search_wiki,
)


def test_descriptor_properties() -> None:
    assert READ_MARKDOWN_DESCRIPTOR.name == "vault.read_markdown"
    assert READ_MARKDOWN_DESCRIPTOR.effect == ToolEffect.READ_ONLY


def test_request_and_result_are_frozen_and_slotted() -> None:
    req = ReadMarkdownRequest(vault_path="test.md")
    res = ReadMarkdownResult(vault_path="test.md", markdown_body="body")

    assert not hasattr(req, "__dict__")
    assert not hasattr(res, "__dict__")

    with pytest.raises(FrozenInstanceError):
        req.vault_path = "changed.md"  # type: ignore

    with pytest.raises(FrozenInstanceError):
        res.markdown_body = "changed"  # type: ignore


def test_valid_markdown_read(tmp_path: Path) -> None:
    md_content = (
        "---\ntitle: test\ntags: [existing, '#nested/topic']\n"
        "topics: [better-topic]\nsecret: do-not-return\n---\n\n# Header\nBody text here.\n"
    )
    (tmp_path / "valid.md").write_text(md_content, encoding="utf-8")

    result = read_markdown(vault_root=tmp_path, request=ReadMarkdownRequest(vault_path="valid.md"))

    assert result.vault_path == "valid.md"
    assert result.markdown_body == "\n# Header\nBody text here.\n"
    assert result.source_tags == ("existing", "nested/topic")
    assert result.source_topics == ("better-topic",)
    # Frontmatter is excluded and body is exact


def test_read_uses_descriptor_io_instead_of_path_reopening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "test.md").write_text("Hello", encoding="utf-8")

    def forbidden(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("path-based reopening was used")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)

    result = read_markdown(
        vault_root=tmp_path,
        request=ReadMarkdownRequest(vault_path="test.md"),
    )

    assert result.markdown_body == "Hello"


def test_absolute_path_rejected_before_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def block_resolve(*args, **kwargs):
        raise AssertionError("Filesystem accessed!")

    monkeypatch.setattr(Path, "resolve", block_resolve)

    with pytest.raises(ToolValidationError, match="Invalid vault path: .*absolute"):
        read_markdown(vault_root=tmp_path, request=ReadMarkdownRequest(vault_path="/absolute.md"))


def test_parent_traversal_rejected_before_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def block_resolve(*args, **kwargs):
        raise AssertionError("Filesystem accessed!")

    monkeypatch.setattr(Path, "resolve", block_resolve)

    with pytest.raises(ToolValidationError, match="Invalid vault path: .*dot"):
        read_markdown(vault_root=tmp_path, request=ReadMarkdownRequest(vault_path="../outside.md"))


def test_backslash_rejected_before_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def block_resolve(*args, **kwargs):
        raise AssertionError("Filesystem accessed!")

    monkeypatch.setattr(Path, "resolve", block_resolve)

    with pytest.raises(ToolValidationError, match="Invalid vault path: .*backslash"):
        read_markdown(vault_root=tmp_path, request=ReadMarkdownRequest(vault_path="dir\\file.md"))


def test_non_markdown_extension_rejected_before_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def block_resolve(*args, **kwargs):
        raise AssertionError("Filesystem accessed!")

    monkeypatch.setattr(Path, "resolve", block_resolve)

    with pytest.raises(ToolValidationError, match="Only Markdown files \\(.md\\) are supported"):
        read_markdown(vault_root=tmp_path, request=ReadMarkdownRequest(vault_path="file.txt"))


def test_missing_file_becomes_not_found(tmp_path: Path) -> None:
    with pytest.raises(ToolNotFoundError, match="Target file not found"):
        read_markdown(vault_root=tmp_path, request=ReadMarkdownRequest(vault_path="missing.md"))


def test_directory_becomes_execution_error(tmp_path: Path) -> None:
    (tmp_path / "dir.md").mkdir()
    with pytest.raises(ToolExecutionError, match="Target is not a regular file"):
        read_markdown(vault_root=tmp_path, request=ReadMarkdownRequest(vault_path="dir.md"))


def test_invalid_utf8_becomes_execution_error(tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe\x00\x00")
    with pytest.raises(ToolExecutionError, match="File is not valid UTF-8"):
        read_markdown(vault_root=tmp_path, request=ReadMarkdownRequest(vault_path="bad.md"))


def test_source_and_inventory_remain_unchanged(tmp_path: Path) -> None:
    # Setup
    md_file = tmp_path / "content.md"
    original_bytes = b"---\ntitle: test\n---\n\n# Header\n"
    md_file.write_bytes(original_bytes)

    original_inventory = sorted(p.name for p in tmp_path.iterdir())

    # Execute
    read_markdown(vault_root=tmp_path, request=ReadMarkdownRequest(vault_path="content.md"))

    # Verify inventory unchanged
    current_inventory = sorted(p.name for p in tmp_path.iterdir())
    assert current_inventory == original_inventory

    # Verify file content unchanged
    current_bytes = md_file.read_bytes()
    assert current_bytes == original_bytes


def test_symlink_escaping_vault_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("Secret", encoding="utf-8")

    link = vault / "link.md"
    link.symlink_to(outside)

    with pytest.raises(ToolValidationError, match="Unsafe vault path"):
        read_markdown(vault_root=vault, request=ReadMarkdownRequest(vault_path="link.md"))


def test_in_vault_symlink_is_also_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    target = vault / "target.md"
    target.write_text("Valid", encoding="utf-8")
    (vault / "link.md").symlink_to(target)

    with pytest.raises(ToolValidationError, match="Unsafe vault path"):
        read_markdown(vault_root=vault, request=ReadMarkdownRequest(vault_path="link.md"))


def test_permission_failure_becomes_execution_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    denied = tmp_path / "denied.md"
    denied.write_text("Hidden", encoding="utf-8")
    original_open = os.open

    def deny_target(
        path: str | bytes | int | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == "denied.md":
            raise PermissionError("denied by test")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", deny_target)

    with pytest.raises(ToolExecutionError, match="Failed to read file"):
        read_markdown(
            vault_root=tmp_path,
            request=ReadMarkdownRequest(vault_path="denied.md"),
        )


def test_no_forbidden_imports() -> None:
    import pathlib

    src_file = (
        pathlib.Path(__file__).parent.parent.parent / "src" / "lifeos" / "facade" / "read_only.py"
    )
    content = src_file.read_text()

    # We do allow registry.file_tracking for FileTrackingError and validate_vault_path, but not other registry things.
    # Actually let's just check the ones explicitly banned:
    assert "lifeos.registry.Registry" not in content
    assert "lifeos.proposals" not in content
    assert "sqlite" not in content.lower()
    assert "pydantic" not in content.lower()
    assert "openai" not in content.lower()


def test_wiki_search_is_read_only_and_scoped_to_wiki(tmp_path: Path) -> None:
    (tmp_path / "wiki").mkdir()
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki" / "learning.md").write_text(
        "---\ntitle: Retrieval Practice\n---\n\nActive recall improves retrieval.\n"
    )
    (tmp_path / "raw" / "source.md").write_text(
        "---\ntitle: Retrieval Source\n---\n\nActive recall raw evidence.\n"
    )

    result = search_wiki(
        vault_root=tmp_path,
        request=WikiSearchRequest(query="active recall", limit=8),
    )

    assert WIKI_SEARCH_DESCRIPTOR.effect == ToolEffect.READ_ONLY
    assert [hit.path for hit in result.hits] == ["wiki/learning.md"]
    assert result.hits[0].title == "Retrieval Practice"
    assert "Active recall" in result.hits[0].excerpt


def test_wiki_search_request_is_bounded() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        WikiSearchRequest(query="   ")
    with pytest.raises(ValueError, match="between 1 and 20"):
        WikiSearchRequest(query="learning", limit=21)


def test_vault_context_is_read_only_and_applies_focus_path_instruction(tmp_path: Path) -> None:
    source = tmp_path / "study/driving-licence/intersections.md"
    source.parent.mkdir(parents=True)
    source.write_text("---\ntitle: Intersections\n---\nRules.\n", encoding="utf-8")
    instructions = tmp_path / "system/instructions.yml"
    instructions.parent.mkdir()
    instructions.write_text(
        "schema_version: 1\ninstructions:\n"
        "  - id: driving-exam\n"
        "    authority: system\n"
        "    scope: path\n"
        "    priority: 100\n"
        "    text: Prioritize exam distinctions.\n"
        "    paths: [study/driving-licence/**]\n",
        encoding="utf-8",
    )

    result = get_vault_context(
        vault_root=tmp_path,
        request=VaultContextRequest(
            question="exam priorities",
            focus_paths=("study/driving-licence/intersections.md",),
        ),
    )

    assert VAULT_CONTEXT_DESCRIPTOR.effect == ToolEffect.READ_ONLY
    assert result.sources[0].path == "study/driving-licence/intersections.md"
    assert [item.id for item in result.instructions] == ["driving-exam"]
