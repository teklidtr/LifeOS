from pathlib import Path

import pytest

from lifeos.facade.errors import ToolExecutionError, ToolValidationError
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


def test_external_reads_require_policy_allowlist_even_with_protected_intent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "journal/private/secret.md", "Secret context phrase.\n")
    _write(
        vault,
        "system/retrieval-policy.yml",
        "schema_version: 1\nexternal_allowed_prefixes: []\n",
    )

    with pytest.raises(ToolValidationError, match="protected-external-deny"):
        read_markdown(
            vault_root=vault,
            request=ReadMarkdownRequest(
                vault_path="journal/private/secret.md",
                allow_protected=True,
                mode="external",
            ),
        )

    _write(
        vault,
        "system/retrieval-policy.yml",
        "schema_version: 1\nexternal_allowed_prefixes:\n  - journal/private\n",
    )
    allowed = read_markdown(
        vault_root=vault,
        request=ReadMarkdownRequest(
            vault_path="journal/private/secret.md",
            allow_protected=True,
            mode="external",
        ),
    )
    assert "Secret context phrase" in allowed.markdown_body


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


def test_policy_filtered_exploration_prunes_invalid_utf8_before_decoding(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/public.md", "Public needle note.\n")
    secret = vault / "journal/private/secret.md"
    secret.parent.mkdir(parents=True)
    secret.write_bytes(b"\xff\xfe\xfd")

    listing = list_vault_paths(vault_root=vault, request=VaultListRequest())
    listed_paths = [item.path for item in listing.entries]
    assert "wiki/public.md" in listed_paths
    assert "journal/private/secret.md" not in listed_paths

    search = search_vault(
        vault_root=vault,
        request=VaultSearchRequest(query="needle"),
    )
    assert [item.path for item in search.hits] == ["wiki/public.md"]

    context = get_vault_context(
        vault_root=vault,
        request=VaultContextRequest(question="needle"),
    )
    assert [item.path for item in context.sources] == ["wiki/public.md"]


def test_context_prunes_protected_yaml_before_instruction_scan(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/public.md", "Public needle note.\n")
    secret = vault / "journal/private/secret-instructions.yml"
    secret.parent.mkdir(parents=True)
    secret.write_bytes(b"\xff\xfe\xfd")

    context = get_vault_context(
        vault_root=vault,
        request=VaultContextRequest(question="needle"),
    )

    assert [item.path for item in context.sources] == ["wiki/public.md"]
    assert all("secret-instructions.yml" not in item.source_path for item in context.diagnostics)


def test_retrieval_policy_symlink_is_rejected_fail_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/public.md", "Public note.\n")
    outside = tmp_path / "outside-policy.yml"
    outside.write_text("schema_version: 1\nprotected_prefixes: []\n", encoding="utf-8")
    system = vault / "system"
    system.mkdir()
    try:
        (system / "retrieval-policy.yml").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ToolExecutionError, match="Retrieval policy is invalid") as error:
        list_vault_paths(vault_root=vault, request=VaultListRequest())

    assert str(outside) not in str(error.value)


def test_vault_list_preserves_allowed_relative_traversal_error(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    wiki = vault / "wiki"
    wiki.mkdir()
    try:
        (wiki / "escape.md").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ToolExecutionError, match="unsafe-symlink.*wiki/escape.md"):
        list_vault_paths(
            vault_root=vault,
            request=VaultListRequest(prefix="wiki"),
        )


def test_search_allowed_io_failure_is_execution_error(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    invalid = vault / "wiki/broken.md"
    invalid.parent.mkdir(parents=True)
    invalid.write_bytes(b"\xff\xfe\xfd")

    with pytest.raises(ToolExecutionError, match="valid UTF-8"):
        search_vault(
            vault_root=vault,
            request=VaultSearchRequest(query="needle"),
        )


def test_search_exposes_parser_diagnostics_for_omitted_allowed_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/good.md", "needle\n")
    _write(vault, "wiki/broken.md", "---\ntitle: Needle\nneedle\n")

    result = search_vault(
        vault_root=vault,
        request=VaultSearchRequest(query="needle"),
    )

    assert [item.path for item in result.hits] == ["wiki/good.md"]
    assert any(item.source_path == "wiki/broken.md" for item in result.diagnostics)


def test_search_bounds_title_and_description_metadata(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    huge_title = "T" * 10_000
    huge_description = "D" * 20_000
    _write(
        vault,
        "wiki/huge.md",
        f"---\ntitle: {huge_title}\ndescription: {huge_description}\n---\nneedle\n",
    )

    result = search_vault(
        vault_root=vault,
        request=VaultSearchRequest(query="needle"),
    )

    assert len(result.hits[0].title) == 512
    assert len(result.hits[0].description) == 1_024


def test_read_many_bounds_title_metadata_separately_from_body_budget(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    huge_title = "T" * 10_000
    _write(vault, "wiki/huge.md", f"---\ntitle: {huge_title}\n---\nbody\n")

    result = read_many(
        vault_root=vault,
        request=VaultReadManyRequest(paths=("wiki/huge.md",), max_characters=1),
    )

    assert result.items[0].markdown_body == "b"
    assert len(result.items[0].title) == 512
    assert result.items[0].truncated is True
    assert result.total_characters == 1


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


def test_vault_links_resolves_nested_markdown_links_relative_to_source(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/source.md", "See [Topic](concepts/topic.md).\n")
    _write(vault, "wiki/concepts/topic.md", "Canonical topic.\n")

    outgoing = inspect_links(
        vault_root=vault,
        request=VaultLinksRequest(path="wiki/source.md", direction="outgoing"),
    )
    assert [item.target_path for item in outgoing.links] == ["wiki/concepts/topic.md"]

    backlinks = inspect_links(
        vault_root=vault,
        request=VaultLinksRequest(path="wiki/concepts/topic.md", direction="backlinks"),
    )
    assert [item.source_path for item in backlinks.links] == ["wiki/source.md"]


def test_markdown_link_stays_source_relative_when_root_candidate_also_exists(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/source.md", "See [Topic](concepts/topic.md).\n")
    _write(vault, "concepts/topic.md", "Root candidate.\n")
    _write(vault, "wiki/concepts/topic.md", "Relative candidate.\n")

    outgoing = inspect_links(
        vault_root=vault,
        request=VaultLinksRequest(path="wiki/source.md", direction="outgoing"),
    )

    assert [item.target_path for item in outgoing.links] == ["wiki/concepts/topic.md"]


def test_path_wikilink_is_not_reinterpreted_as_source_relative(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/source.md", "See [[concepts/topic]].\n")
    _write(vault, "wiki/concepts/topic.md", "Relative-only candidate.\n")

    outgoing = inspect_links(
        vault_root=vault,
        request=VaultLinksRequest(path="wiki/source.md", direction="outgoing"),
    )

    assert outgoing.links == ()


def test_vault_links_supports_deterministic_continuation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/source.md", "See [[a]], [[b]], and [[c]].\n")
    for name in ("a", "b", "c"):
        _write(vault, f"wiki/{name}.md", f"{name}\n")

    first = inspect_links(
        vault_root=vault,
        request=VaultLinksRequest(
            path="wiki/source.md",
            direction="outgoing",
            limit=2,
        ),
    )
    assert first.truncated is True
    assert first.next_offset == 2

    second = inspect_links(
        vault_root=vault,
        request=VaultLinksRequest(
            path="wiki/source.md",
            direction="outgoing",
            limit=2,
            offset=first.next_offset or 0,
        ),
    )
    assert [item.target_path for item in (*first.links, *second.links)] == [
        "wiki/a.md",
        "wiki/b.md",
        "wiki/c.md",
    ]
    assert second.truncated is False
    assert second.next_offset is None


def test_vault_links_surfaces_requested_source_parse_failure(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/broken.md", "---\ntitle: Broken\nSee [[topic]].\n")
    _write(vault, "wiki/topic.md", "Topic.\n")

    with pytest.raises(ToolExecutionError, match="Requested note could not be parsed"):
        inspect_links(
            vault_root=vault,
            request=VaultLinksRequest(path="wiki/broken.md", direction="outgoing"),
        )


def test_vault_links_reports_malformed_backlink_candidates(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(vault, "wiki/target.md", "Target.\n")
    _write(vault, "wiki/broken.md", "---\ntitle: Broken\nSee [[target]].\n")

    result = inspect_links(
        vault_root=vault,
        request=VaultLinksRequest(path="wiki/target.md", direction="backlinks"),
    )

    assert result.links == ()
    assert any(
        item.code == "link-source-parse-failed" and item.source_path == "wiki/broken.md"
        for item in result.diagnostics
    )
