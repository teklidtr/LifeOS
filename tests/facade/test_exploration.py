from pathlib import Path

import pytest

from lifeos.facade.errors import ToolValidationError
from lifeos.facade.exploration import (
    VaultLinksRequest,
    VaultListRequest,
    VaultReadManyRequest,
    VaultSearchRequest,
    inspect_links,
    list_vault_paths,
    read_many,
    search_vault,
)


def _write(vault: Path, path: str, body: str) -> None:
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_exploration_supports_find_grep_cat_and_link_crawl(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault,
        "wiki/learning/retrieval.md",
        "---\ntitle: Retrieval Practice\ndescription: Durable learning method\n---\n"
        "Retrieval practice strengthens recall. See [[spacing]].\n",
    )
    _write(
        vault,
        "wiki/learning/spacing.md",
        "---\ntitle: Spacing\n---\nSpaced review complements retrieval practice.\n",
    )
    _write(
        vault,
        "study/exam.md",
        "---\ntitle: Exam Notes\n---\nUse [[../wiki/learning/retrieval]].\n",
    )

    listing = list_vault_paths(
        vault_root=vault,
        request=VaultListRequest(prefix="wiki", limit=20),
    )
    listed = {(item.path, item.kind) for item in listing.entries}
    assert ("wiki/learning", "folder") in listed
    assert ("wiki/learning/retrieval.md", "file") in listed

    search = search_vault(
        vault_root=vault,
        request=VaultSearchRequest(query="retrieval practice", limit=10),
    )
    assert search.hits[0].path == "wiki/learning/retrieval.md"
    assert "retrieval" in search.hits[0].matched_terms

    comparison = read_many(
        vault_root=vault,
        request=VaultReadManyRequest(
            paths=("wiki/learning/retrieval.md", "wiki/learning/spacing.md"),
            max_characters=10_000,
        ),
    )
    assert [item.path for item in comparison.items] == [
        "wiki/learning/retrieval.md",
        "wiki/learning/spacing.md",
    ]
    assert comparison.truncated is False
    assert all(item.content_hash.startswith("sha256:") for item in comparison.items)

    links = inspect_links(
        vault_root=vault,
        request=VaultLinksRequest(path="wiki/learning/retrieval.md"),
    )
    assert any(
        item.direction == "outgoing" and item.target_path == "wiki/learning/spacing.md"
        for item in links.links
    )


def test_exploration_protected_scopes_are_default_deny(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/public.md", "Public searchable phrase.\n")
    _write(vault, "journal/private/secret.md", "Private searchable phrase.\n")

    listing = list_vault_paths(vault_root=vault, request=VaultListRequest())
    paths = {item.path for item in listing.entries}
    assert "wiki/public.md" in paths
    assert "journal/private/secret.md" not in paths

    search = search_vault(
        vault_root=vault,
        request=VaultSearchRequest(query="searchable phrase"),
    )
    assert [item.path for item in search.hits] == ["wiki/public.md"]

    with pytest.raises(ToolValidationError):
        read_many(
            vault_root=vault,
            request=VaultReadManyRequest(paths=("journal/private/secret.md",)),
        )

    explicit = read_many(
        vault_root=vault,
        request=VaultReadManyRequest(
            paths=("journal/private/secret.md",),
            allow_protected=True,
        ),
    )
    assert explicit.items[0].path == "journal/private/secret.md"


def test_read_many_enforces_total_output_budget(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/a.md", "abcdefghij")
    _write(vault, "wiki/b.md", "klmnopqrst")

    result = read_many(
        vault_root=vault,
        request=VaultReadManyRequest(
            paths=("wiki/a.md", "wiki/b.md"),
            max_characters=12,
        ),
    )

    assert result.total_characters == 12
    assert result.truncated is True
    assert result.items[1].truncated is True
