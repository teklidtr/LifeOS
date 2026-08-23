"""Small structural wiki layout for agent-generated knowledge pages.

The roles here are filing roles, not a domain ontology. They intentionally stay
small and generic so LifeOS can distinguish source summaries, named entities,
concepts, and reusable syntheses without encoding domain-specific semantics in
folder names.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal, cast

WikiPageKind = Literal["source", "entity", "concept", "synthesis"]

WIKI_PAGE_FOLDERS: dict[WikiPageKind, str] = {
    "source": "wiki/sources",
    "entity": "wiki/entities",
    "concept": "wiki/concepts",
    "synthesis": "wiki/syntheses",
}

_FOLDER_TO_KIND = {folder: kind for kind, folder in WIKI_PAGE_FOLDERS.items()}
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class WikiLayoutError(ValueError):
    pass


def validate_wiki_page_kind(value: str) -> WikiPageKind:
    if value not in WIKI_PAGE_FOLDERS:
        choices = ", ".join(WIKI_PAGE_FOLDERS)
        raise WikiLayoutError(f"page_kind must be one of: {choices}")
    return cast(WikiPageKind, value)


def validate_wiki_slug(slug: str) -> str:
    if not isinstance(slug, str):
        raise WikiLayoutError("slug must be a string")
    if not _SLUG_RE.fullmatch(slug):
        raise WikiLayoutError(
            "slug must use lowercase ASCII kebab-case (letters, numbers, single hyphens)"
        )
    return slug


def typed_wiki_target(page_kind: str, slug: str) -> str:
    kind = validate_wiki_page_kind(page_kind)
    normalized_slug = validate_wiki_slug(slug)
    return f"{WIKI_PAGE_FOLDERS[kind]}/{normalized_slug}.md"


def infer_wiki_page_kind(target_path: str) -> WikiPageKind | None:
    normalized = PurePosixPath(target_path)
    if normalized.suffix != ".md":
        return None
    parent = normalized.parent.as_posix()
    return _FOLDER_TO_KIND.get(parent)


def is_lazy_wiki_role_parent(parent_path: str) -> bool:
    """Return whether application may lazily create this exact structural folder."""

    return parent_path in _FOLDER_TO_KIND

MAX_EMERGENT_WIKI_PARENT_DEPTH = 6
_GENERATED_EMERGENT_ROOTS = frozenset({"wiki", "flashcards"})


def is_emergent_generated_parent(parent_path: str) -> bool:
    """Return whether reviewed generated content may materialize this parent.

    Semantic folder names are not enumerated. Only bounded nesting beneath an
    already-existing canonical generated root is eligible for lazy creation.
    """

    normalized = PurePosixPath(parent_path)
    parts = normalized.parts
    if len(parts) < 2 or parts[0] not in _GENERATED_EMERGENT_ROOTS:
        return False
    nested_depth = len(parts) - 1
    return nested_depth <= MAX_EMERGENT_WIKI_PARENT_DEPTH


def is_emergent_wiki_parent(parent_path: str) -> bool:
    """Return whether generated ingestion may materialize this wiki parent.

    Folder names are deliberately not enumerated. The mutation boundary is the
    canonical ``wiki/`` root plus a bounded nesting depth; semantic organization
    is left to the reviewing agent and user.
    """

    normalized = PurePosixPath(parent_path)
    return normalized.parts[:1] == ("wiki",) and is_emergent_generated_parent(parent_path)
