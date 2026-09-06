import pytest

from lifeos.ingestion.taxonomy import (
    MAX_PROPOSED_TAGS,
    MAX_SOURCE_TAXONOMY_VALUES,
    TagValidationError,
    extract_source_taxonomy,
    validate_proposed_tags,
)


def test_source_taxonomy_is_bounded_normalized_evidence() -> None:
    taxonomy = extract_source_taxonomy(
        {
            "tags": [" # Acil Yardım ", "acil yardım", 42, ""],
            "topics": " Ehliyet Sınavı ",
            "private": "must not be exposed",
        }
    )

    assert taxonomy.tags == ("Acil Yardım",)
    assert taxonomy.topics == ("Ehliyet Sınavı",)
    assert not hasattr(taxonomy, "private")


def test_source_taxonomy_ignores_multiline_values_and_caps_exposure() -> None:
    taxonomy = extract_source_taxonomy(
        {
            "topics": ["unsafe\nheading"]
            + [f"topic {index}" for index in range(MAX_SOURCE_TAXONOMY_VALUES + 5)]
        }
    )

    assert len(taxonomy.topics) == MAX_SOURCE_TAXONOMY_VALUES
    assert taxonomy.topics[0] == "topic 0"
    assert taxonomy.topics[-1] == f"topic {MAX_SOURCE_TAXONOMY_VALUES - 1}"


@pytest.mark.parametrize(
    ("tags", "message"),
    [
        (("Uppercase",), "lowercase"),
        (("ilk-yardim", "ilk-yardim"), "duplicates"),
        (("space tag",), "may contain only"),
        ((" tag",), "surrounding whitespace"),
        (("e\u0301",), "NFC"),
        (tuple(f"tag-{index}" for index in range(MAX_PROPOSED_TAGS + 1)), "more than"),
    ],
)
def test_invalid_proposed_tags_fail_deterministically(tags: tuple[str, ...], message: str) -> None:
    with pytest.raises(TagValidationError, match=message):
        validate_proposed_tags(tags)
