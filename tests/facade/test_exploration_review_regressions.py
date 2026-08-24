from pathlib import Path

import pytest

from lifeos.facade.errors import ToolValidationError
from lifeos.facade.exploration import (
    VaultLinksRequest,
    VaultListRequest,
    VaultSearchRequest,
    inspect_links,
    list_vault_paths,
    search_vault,
)
from lifeos.facade.read_only import (
    ReadMarkdownRequest,
    VaultContextRequest,
    get_vault_context,
    read_markdown,
)


def _write(vault: Path, path: str, body: str) -> None:
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_composed_read_facades_default_deny_protected_content(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/public.md", "Public context phrase.\n")
    _write(vault, "journal/private/secret.md", "Secret context phrase.\n")

    with pytest.raises(ToolValidationError, match="protected-default-deny"):
        read_markdown(
            vault_root=vault,
            request=ReadMarkdownRequest(vault_path="journal/private/secret.md"),
        )

    explicit_read = read_markdown(
        vault_root=vault,
        request=ReadMarkdownRequest(
            vault_path="journal/private/secret.md",
            allow_protected=True,
        ),
    )
    assert "Secret context phrase" in explicit_read.markdown_body

    with pytest.raises(ToolValidationError, match="not available for retrieval"):
        get_vault_context(
            vault_root=vault,
            request=VaultContextRequest(
                question="Secret context phrase",
                focus_paths=("journal/private/secret.md",),
            ),
        )

    default_context = get_vault_context(
        vault_root=vault,
        request=VaultContextRequest(question="Secret context phrase"),
    )
    assert all(item.path != "journal/private/secret.md" for item in default_context.sources)

    explicit_context = get_vault_context(
        vault_root=vault,
        request=VaultContextRequest(
            question="Secret context phrase",
            focus_paths=("journal/private/secret.md",),
            allow_protected=True,
        ),
    )
    assert explicit_context.sources[0].path == "journal/private/secret.md"


def test_search_filters_policy_before_ranking_cap(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    for index in range(205):
        _write(
            vault,
            f"journal/private/{index:03d}.md",
            "---\ntitle: Needle\n---\nneedle\n",
        )
    _write(vault, "wiki/z-allowed.md", "needle\n")

    result = search_vault(
        vault_root=vault,
        request=VaultSearchRequest(query="needle", limit=10),
    )

    assert [item.path for item in result.hits] == ["wiki/z-allowed.md"]


def test_vault_list_supports_stable_continuation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    for name in ("a", "b", "c", "d"):
        _write(vault, f"wiki/{name}.md", f"{name}\n")

    collected: list[str] = []
    after: str | None = None
    while True:
        page = list_vault_paths(
            vault_root=vault,
            request=VaultListRequest(prefix="wiki", limit=2, after=after),
        )
        collected.extend(item.path for item in page.entries)
        if not page.truncated:
            assert page.next_after is None
            break
        assert page.next_after == page.entries[-1].path
        after = page.next_after

    assert collected == ["wiki", "wiki/a.md", "wiki/b.md", "wiki/c.md", "wiki/d.md"]
    assert len(collected) == len(set(collected))


def test_vault_links_resolves_unique_basename_and_rejects_ambiguous_targets(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/source.md", "See [[topic]].\n")
    _write(vault, "wiki/concepts/topic.md", "Canonical topic.\n")

    outgoing = inspect_links(
        vault_root=vault,
        request=VaultLinksRequest(path="wiki/source.md", direction="outgoing"),
    )
    assert any(item.target_path == "wiki/concepts/topic.md" for item in outgoing.links)

    backlinks = inspect_links(
        vault_root=vault,
        request=VaultLinksRequest(path="wiki/concepts/topic.md", direction="backlinks"),
    )
    assert any(item.source_path == "wiki/source.md" for item in backlinks.links)

    _write(vault, "wiki/other/topic.md", "Another topic.\n")
    ambiguous = inspect_links(
        vault_root=vault,
        request=VaultLinksRequest(path="wiki/source.md", direction="outgoing"),
    )
    assert not ambiguous.links
