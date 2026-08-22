import pytest

from lifeos.wiki.layout import (
    WikiLayoutError,
    infer_wiki_page_kind,
    is_lazy_wiki_role_parent,
    typed_wiki_target,
)


@pytest.mark.parametrize(
    ("page_kind", "slug", "target"),
    [
        ("source", "paper-2026", "wiki/sources/paper-2026.md"),
        ("entity", "andrej-karpathy", "wiki/entities/andrej-karpathy.md"),
        ("concept", "active-recall", "wiki/concepts/active-recall.md"),
        ("synthesis", "learning-systems", "wiki/syntheses/learning-systems.md"),
    ],
)
def test_typed_wiki_target_maps_small_structural_roles(
    page_kind: str, slug: str, target: str
) -> None:
    assert typed_wiki_target(page_kind, slug) == target
    assert infer_wiki_page_kind(target) == page_kind
    assert is_lazy_wiki_role_parent(target.rsplit("/", 1)[0])


@pytest.mark.parametrize(
    "slug",
    ["Active-Recall", "active recall", "active_recall", "active--recall", "active/recall"],
)
def test_typed_wiki_target_rejects_noncanonical_slugs(slug: str) -> None:
    with pytest.raises(WikiLayoutError, match="lowercase ASCII kebab-case"):
        typed_wiki_target("concept", slug)


def test_arbitrary_wiki_subfolder_is_not_a_lazy_role_parent() -> None:
    assert infer_wiki_page_kind("wiki/topics/active-recall.md") is None
    assert not is_lazy_wiki_role_parent("wiki/topics")
