import pytest
from pathlib import Path
from typing import Any

from lifeos.ingestion.provenance import (
    LifeOSProvenance,
    ProvenanceGenerator,
    ProvenanceSource,
    ProvenanceValidationError,
    extract_provenance,
    merge_provenance_sources,
    provenance_to_frontmatter_value,
)
from lifeos.markdown.parser import parse_markdown_note


def valid_raw_mapping() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "sources": [
            {
                "path": "study/example.md",
                "content_hash": "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            }
        ],
        "generator": {
            "id": "lifeos.ingestion.wiki",
            "version": "1.0",
            "prompt_schema_version": "v1",
        },
        "created_at": "2026-07-13T17:00:00Z",
    }


def test_valid_one_source_mapping_parses() -> None:
    raw = valid_raw_mapping()
    prov = extract_provenance({"lifeos_provenance": raw})
    assert prov is not None
    assert prov.schema_version == 1
    assert len(prov.sources) == 1
    assert prov.sources[0].path == "study/example.md"
    assert prov.sources[0].content_hash == "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    assert prov.generator.id == "lifeos.ingestion.wiki"
    assert prov.generator.version == "1.0"
    assert prov.generator.prompt_schema_version == "v1"
    assert prov.generator.model_id is None
    assert prov.created_at == "2026-07-13T17:00:00Z"


def test_absent_block_returns_none() -> None:
    assert extract_provenance({}) is None


def test_typed_model_converts_to_deterministic_mapping() -> None:
    prov = LifeOSProvenance(
        schema_version=1,
        sources=(ProvenanceSource(
            path="study/example.md",
            content_hash="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        ),),
        generator=ProvenanceGenerator(
            id="lifeos.ingestion.wiki",
            version="1.0",
            prompt_schema_version="v1",
            model_id=None,
        ),
        created_at="2026-07-13T17:00:00Z",
    )
    mapping = provenance_to_frontmatter_value(prov)
    assert list(mapping.keys()) == ["schema_version", "sources", "generator", "created_at"]
    assert list(mapping["generator"].keys()) == ["id", "version", "prompt_schema_version"]  # type: ignore[union-attr]


def test_mapping_key_order_is_deterministic() -> None:
    prov = LifeOSProvenance(
        schema_version=1,
        sources=(ProvenanceSource(
            path="study/example.md",
            content_hash="sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        ),),
        generator=ProvenanceGenerator(
            id="lifeos.ingestion.wiki",
            version="1.0",
            prompt_schema_version="v1",
            model_id="gemini-pro",
        ),
        created_at="2026-07-13T17:00:00Z",
    )
    mapping = provenance_to_frontmatter_value(prov)
    assert list(mapping["generator"].keys()) == [  # type: ignore[union-attr]
        "id", "version", "prompt_schema_version", "model_id"
    ]


def test_parse_and_mapping_round_trip() -> None:
    raw = valid_raw_mapping()
    prov = extract_provenance({"lifeos_provenance": raw})
    assert prov is not None
    assert provenance_to_frontmatter_value(prov) == raw


def test_multiple_sources_parse_and_round_trip_in_version_1() -> None:
    raw = valid_raw_mapping()
    raw["sources"].append({
        "path": "journal/example.md",
        "content_hash": "sha256:" + "a" * 64,
    })
    prov = extract_provenance({"lifeos_provenance": raw})
    assert prov is not None
    assert [source.path for source in prov.sources] == ["study/example.md", "journal/example.md"]
    assert provenance_to_frontmatter_value(prov) == raw


def test_merge_exact_snapshot_deduplicates_and_changed_hash_is_retained() -> None:
    first = ProvenanceSource("notes/creatine.md", "sha256:" + "a" * 64)
    same = ProvenanceSource("notes/creatine.md", "sha256:" + "a" * 64)
    changed = ProvenanceSource("notes/creatine.md", "sha256:" + "b" * 64)
    assert merge_provenance_sources((first,), same) == (first,)
    assert merge_provenance_sources((first,), changed) == (first, changed)


def test_unsupported_schema_version_rejected() -> None:
    raw = valid_raw_mapping()
    raw["schema_version"] = 2
    with pytest.raises(ProvenanceValidationError, match="schema_version must be 1"):
        extract_provenance({"lifeos_provenance": raw})


def test_boolean_schema_version_rejected() -> None:
    raw = valid_raw_mapping()
    raw["schema_version"] = True
    with pytest.raises(ProvenanceValidationError, match="schema_version must be an integer"):
        extract_provenance({"lifeos_provenance": raw})


def test_empty_source_list_rejected() -> None:
    raw = valid_raw_mapping()
    raw["sources"] = []
    with pytest.raises(ProvenanceValidationError, match="at least one source for schema_version 1"):
        extract_provenance({"lifeos_provenance": raw})


def test_absolute_path_rejected() -> None:
    raw = valid_raw_mapping()
    raw["sources"][0]["path"] = "/absolute/path.md"
    with pytest.raises(ProvenanceValidationError, match="cannot be absolute"):
        extract_provenance({"lifeos_provenance": raw})


def test_parent_traversal_rejected() -> None:
    raw = valid_raw_mapping()
    raw["sources"][0]["path"] = "study/../example.md"
    with pytest.raises(ProvenanceValidationError, match="parent traversal"):
        extract_provenance({"lifeos_provenance": raw})


def test_backslash_path_rejected() -> None:
    raw = valid_raw_mapping()
    raw["sources"][0]["path"] = "study\\example.md"
    with pytest.raises(ProvenanceValidationError, match="contain backslashes"):
        extract_provenance({"lifeos_provenance": raw})


def test_non_normalized_path_rejected() -> None:
    raw = valid_raw_mapping()
    raw["sources"][0]["path"] = "study/./example.md"
    with pytest.raises(ProvenanceValidationError, match="not normalized"):
        extract_provenance({"lifeos_provenance": raw})


def test_malformed_sha256_rejected() -> None:
    raw = valid_raw_mapping()
    raw["sources"][0]["content_hash"] = "md5:123"
    with pytest.raises(ProvenanceValidationError, match="canonical form: sha256:"):
        extract_provenance({"lifeos_provenance": raw})


def test_uppercase_sha256_rejected() -> None:
    raw = valid_raw_mapping()
    raw["sources"][0]["content_hash"] = "sha256:1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF"
    with pytest.raises(ProvenanceValidationError, match="lowercase hexadecimal"):
        extract_provenance({"lifeos_provenance": raw})


def test_empty_generator_id_rejected() -> None:
    raw = valid_raw_mapping()
    raw["generator"]["id"] = "   "
    with pytest.raises(ProvenanceValidationError, match="generator id must be non-empty"):
        extract_provenance({"lifeos_provenance": raw})


def test_empty_generator_version_rejected() -> None:
    raw = valid_raw_mapping()
    raw["generator"]["version"] = ""
    with pytest.raises(ProvenanceValidationError, match="generator version must be non-empty"):
        extract_provenance({"lifeos_provenance": raw})


def test_empty_prompt_schema_version_rejected() -> None:
    raw = valid_raw_mapping()
    raw["generator"]["prompt_schema_version"] = ""
    with pytest.raises(ProvenanceValidationError, match="generator prompt_schema_version must be non-empty"):
        extract_provenance({"lifeos_provenance": raw})


def test_empty_model_id_rejected_when_present() -> None:
    raw = valid_raw_mapping()
    raw["generator"]["model_id"] = ""
    with pytest.raises(ProvenanceValidationError, match="generator model_id must be non-empty"):
        extract_provenance({"lifeos_provenance": raw})


def test_model_id_absence_follows_rule() -> None:
    raw = valid_raw_mapping()
    prov = extract_provenance({"lifeos_provenance": raw})
    assert prov is not None
    mapped = provenance_to_frontmatter_value(prov)
    assert "model_id" not in mapped["generator"]  # type: ignore[operator]


def test_noncanonical_timestamp_rejected() -> None:
    raw = valid_raw_mapping()
    raw["created_at"] = "2026-07-13 17:00:00"
    with pytest.raises(ProvenanceValidationError, match="strictly formatted as YYYY-MM-DDTHH:MM:SSZ"):
        extract_provenance({"lifeos_provenance": raw})


def test_fractional_timestamp_rejected() -> None:
    raw = valid_raw_mapping()
    raw["created_at"] = "2026-07-13T17:00:00.123Z"
    with pytest.raises(ProvenanceValidationError, match="strictly formatted as YYYY-MM-DDTHH:MM:SSZ"):
        extract_provenance({"lifeos_provenance": raw})


def test_valid_timestamp_preserved_exactly() -> None:
    raw = valid_raw_mapping()
    prov = extract_provenance({"lifeos_provenance": raw})
    assert prov is not None
    assert prov.created_at == "2026-07-13T17:00:00Z"


def test_unknown_fields_rejected() -> None:
    raw = valid_raw_mapping()
    raw["some_extra"] = 123
    with pytest.raises(ProvenanceValidationError, match="Unknown field in lifeos_provenance: some_extra"):
        extract_provenance({"lifeos_provenance": raw})


def test_provenance_contains_no_ownership_behavior() -> None:
    raw = valid_raw_mapping()
    prov = extract_provenance({"lifeos_provenance": raw})
    assert prov is not None
    assert not hasattr(prov, "write_generated_file")


def test_integration_nested_mapping_survives_existing_parser(tmp_path: Path) -> None:
    md = """---
id: abc
lifeos_provenance:
  schema_version: 1
  sources:
    - path: study/example.md
      content_hash: sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef
    - path: journal/example.md
      content_hash: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  generator:
    id: lifeos.ingestion.wiki
    version: "1.0"
    prompt_schema_version: "v1"
  created_at: "2026-07-13T17:00:00Z"
---
# Body
"""
    note = parse_markdown_note(Path("dummy.md"), content=md)
    assert not note.findings
    assert isinstance(note.frontmatter["lifeos_provenance"]["created_at"], str)  # type: ignore[index]
    prov = extract_provenance(note.frontmatter)
    assert prov is not None
    assert prov.schema_version == 1
    assert [source.path for source in prov.sources] == ["study/example.md", "journal/example.md"]
    assert prov.generator.id == "lifeos.ingestion.wiki"


def test_unknown_source_field_rejected() -> None:
    raw = valid_raw_mapping()
    raw["sources"][0]["extra_field"] = "value"
    with pytest.raises(ProvenanceValidationError, match="Unknown field in source: extra_field"):
        extract_provenance({"lifeos_provenance": raw})


def test_unknown_generator_field_rejected() -> None:
    raw = valid_raw_mapping()
    raw["generator"]["extra_field"] = "value"
    with pytest.raises(ProvenanceValidationError, match="Unknown field in generator: extra_field"):
        extract_provenance({"lifeos_provenance": raw})
