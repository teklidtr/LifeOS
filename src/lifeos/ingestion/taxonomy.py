"""Bounded source taxonomy extraction and proposed wiki-tag validation."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MAX_PROPOSED_TAGS = 12
MAX_TAG_LENGTH = 64
MAX_SOURCE_TAXONOMY_VALUES = 32
MAX_SOURCE_TAXONOMY_LENGTH = 128


class TagValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SourceTaxonomy:
    tags: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()


def _source_values(value: Any) -> tuple[str, ...]:
    values: Sequence[Any]
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        if len(result) >= MAX_SOURCE_TAXONOMY_VALUES:
            break
        if not isinstance(item, str):
            continue
        normalized = unicodedata.normalize("NFC", item).strip()
        if normalized.startswith("#"):
            normalized = normalized[1:].strip()
        if (
            not normalized
            or len(normalized) > MAX_SOURCE_TAXONOMY_LENGTH
            or "\n" in normalized
            or "\r" in normalized
            or normalized.casefold() in seen
        ):
            continue
        seen.add(normalized.casefold())
        result.append(normalized)
    return tuple(result)


def extract_source_taxonomy(frontmatter: Mapping[str, Any]) -> SourceTaxonomy:
    return SourceTaxonomy(
        tags=_source_values(frontmatter.get("tags")),
        topics=_source_values(frontmatter.get("topics")),
    )


def validate_proposed_tags(tags: Sequence[str] | None) -> tuple[str, ...]:
    if tags is None:
        return ()
    if isinstance(tags, (str, bytes)):
        raise TagValidationError("tags must be a list of strings")
    if len(tags) > MAX_PROPOSED_TAGS:
        raise TagValidationError(f"tags cannot contain more than {MAX_PROPOSED_TAGS} values")
    result: list[str] = []
    seen: set[str] = set()
    for index, tag in enumerate(tags):
        if not isinstance(tag, str):
            raise TagValidationError(f"tags[{index}] must be a string")
        if tag != unicodedata.normalize("NFC", tag):
            raise TagValidationError(f"tags[{index}] must use NFC Unicode normalization")
        if not tag or tag != tag.strip():
            raise TagValidationError(
                f"tags[{index}] must be non-empty without surrounding whitespace"
            )
        if len(tag) > MAX_TAG_LENGTH:
            raise TagValidationError(f"tags[{index}] exceeds {MAX_TAG_LENGTH} characters")
        if tag != tag.casefold():
            raise TagValidationError(f"tags[{index}] must be lowercase")
        if not tag[0].isalnum() or not tag[-1].isalnum():
            raise TagValidationError(f"tags[{index}] must start and end with a letter or number")
        if any(not (character.isalnum() or character in "-_/") for character in tag):
            raise TagValidationError(
                f"tags[{index}] may contain only letters, numbers, hyphens, underscores, or slashes"
            )
        folded = tag.casefold()
        if folded in seen:
            raise TagValidationError(f"tags[{index}] duplicates an earlier tag")
        seen.add(folded)
        result.append(tag)
    return tuple(result)


def validate_tag_rationale(rationale: str | None) -> str | None:
    if rationale is None:
        return None
    if not isinstance(rationale, str):
        raise TagValidationError("tag_rationale must be a string")
    if not rationale or rationale != rationale.strip():
        raise TagValidationError("tag_rationale must be non-empty without surrounding whitespace")
    if "\n" in rationale or "\r" in rationale:
        raise TagValidationError("tag_rationale must be one line")
    if len(rationale) > 500:
        raise TagValidationError("tag_rationale cannot exceed 500 characters")
    return rationale
