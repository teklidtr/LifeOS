from datetime import datetime, timezone, timedelta
import pytest
import json
from dataclasses import FrozenInstanceError

from lifeos.proposals import (
    ProposalStatus,
    ProposalSchemaError,
    validate_metadata,
    serialize_metadata,
    generate_proposal_id,
)


def test_valid_minimal_metadata():
    data = {
        "id": "prop-20260712T184129Z-a1b2c3d4",
        "schema_version": 1,
        "patch_schema_version": 1,
        "title": "Minimal",
        "description": "desc",
        "status": "draft",
        "risk": "low",
        "created_at": "2026-07-12T18:41:29Z",
        "created_by": "system",
    }
    meta = validate_metadata(data)
    assert meta.id == "prop-20260712T184129Z-a1b2c3d4"
    assert meta.status == ProposalStatus.DRAFT
    assert meta.related_goals == ()
    assert meta.extensions == {}


def test_valid_complete_metadata():
    data = {
        "id": "prop-20260712T184129Z-a1b2c3d4",
        "schema_version": 1,
        "patch_schema_version": 2,
        "title": "Complete",
        "description": "desc",
        "status": "applied",
        "risk": "high",
        "created_at": "2026-07-12T18:41:29Z",
        "created_by": "human",
        "approved_at": "2026-07-12T19:00:00Z",
        "applied_at": "2026-07-12T19:05:00Z",
        "related_goals": ["goal-1"],
        "related_sources": ["source-1"],
        "extensions": {"test": [1, {"nested": True}]},
    }
    meta = validate_metadata(data)
    assert meta.status == ProposalStatus.APPLIED
    assert meta.related_goals == ("goal-1",)
    assert meta.extensions["test"][1]["nested"] is True


def test_invalid_proposal_ids():
    base = {
        "schema_version": 1,
        "patch_schema_version": 1,
        "title": "T",
        "description": "D",
        "status": "draft",
        "risk": "low",
        "created_at": "2026-07-12T18:41:29Z",
        "created_by": "system",
    }

    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({**base, "id": "prop-20260712-a1b2c3d4"})
    assert exc.value.code == "invalid_format"

    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({**base, "id": "prop-20260712T184129Z-A1B2C3D4"})  # uppercase hex
    assert exc.value.code == "invalid_format"


def test_invalid_statuses_and_risk():
    base = {
        "id": "prop-20260712T184129Z-a1b2c3d4",
        "schema_version": 1,
        "patch_schema_version": 1,
        "title": "T",
        "description": "D",
        "created_at": "2026-07-12T18:41:29Z",
        "created_by": "system",
    }

    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({**base, "status": "stale", "risk": "low"})
    assert exc.value.code == "invalid_value"
    assert exc.value.field_path == "status"

    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({**base, "status": "draft", "risk": "extreme"})
    assert exc.value.code == "invalid_value"
    assert exc.value.field_path == "risk"


def test_invalid_timestamps():
    base = {
        "id": "prop-20260712T184129Z-a1b2c3d4",
        "schema_version": 1,
        "patch_schema_version": 1,
        "title": "T",
        "description": "D",
        "status": "draft",
        "risk": "low",
        "created_by": "system",
    }

    # Missing T/Z
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({**base, "created_at": "2026-07-12 18:41:29"})
    assert exc.value.code == "invalid_format"

    # Fractional seconds
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({**base, "created_at": "2026-07-12T18:41:29.123Z"})
    assert exc.value.code == "invalid_format"

    # Offsets
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({**base, "created_at": "2026-07-12T18:41:29+03:00"})
    assert exc.value.code == "invalid_format"

    # YAML datetime object instead of string
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({**base, "created_at": datetime.now()})
    assert exc.value.code == "invalid_type"

    # Invalid calendar date (February 30th)
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({**base, "created_at": "2026-02-30T12:00:00Z"})
    assert exc.value.code == "invalid_value"

    # Invalid month (13)
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({**base, "created_at": "2026-13-01T12:00:00Z"})
    assert exc.value.code == "invalid_value"

    # Invalid hour (25)
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({**base, "created_at": "2026-07-12T25:00:00Z"})
    assert exc.value.code == "invalid_value"


def test_missing_required_fields():
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({"title": "Only Title"})
    assert exc.value.code == "missing_field"


def test_unknown_top_level_fields():
    base = {
        "id": "prop-20260712T184129Z-a1b2c3d4",
        "schema_version": 1,
        "patch_schema_version": 1,
        "title": "T",
        "description": "D",
        "status": "draft",
        "risk": "low",
        "created_at": "2026-07-12T18:41:29Z",
        "created_by": "system",
        "unknown_field": "error",
    }
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata(base)
    assert exc.value.code == "unknown_field"
    assert exc.value.field_path == "unknown_field"


def test_boolean_schema_version():
    base = {
        "id": "prop-20260712T184129Z-a1b2c3d4",
        "schema_version": True,
        "patch_schema_version": 1,
        "title": "T",
        "description": "D",
        "status": "draft",
        "risk": "low",
        "created_at": "2026-07-12T18:41:29Z",
        "created_by": "system",
    }
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata(base)
    assert exc.value.code == "invalid_type"
    assert exc.value.field_path == "schema_version"


def test_lifecycle_timestamp_consistency():
    base = {
        "id": "prop-20260712T184129Z-a1b2c3d4",
        "schema_version": 1,
        "patch_schema_version": 1,
        "title": "T",
        "description": "D",
        "status": "approved",
        "risk": "low",
        "created_at": "2026-07-12T18:41:29Z",
        "created_by": "system",
    }

    # Approved but missing approved_at
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata(base)
    assert exc.value.code == "lifecycle_mismatch"
    assert exc.value.field_path == "approved_at"

    # Draft but has approved_at
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata({**base, "status": "draft", "approved_at": "2026-07-12T19:00:00Z"})
    assert exc.value.code == "lifecycle_mismatch"
    assert exc.value.field_path == "approved_at"


def test_chronological_timestamp_ordering():
    base = {
        "id": "prop-20260712T184129Z-a1b2c3d4",
        "schema_version": 1,
        "patch_schema_version": 1,
        "title": "T",
        "description": "D",
        "status": "approved",
        "risk": "low",
        "created_at": "2026-07-12T18:41:29Z",
        "created_by": "system",
        "approved_at": "2026-07-12T18:00:00Z",  # Before created_at
    }
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata(base)
    assert exc.value.code == "chronology_error"
    assert exc.value.field_path == "approved_at"


def test_deep_immutability():
    data = {
        "id": "prop-20260712T184129Z-a1b2c3d4",
        "schema_version": 1,
        "patch_schema_version": 1,
        "title": "T",
        "description": "D",
        "status": "draft",
        "risk": "low",
        "created_at": "2026-07-12T18:41:29Z",
        "created_by": "system",
        "related_goals": ["g1"],
        "extensions": {"nested": {"list": [1, 2]}},
    }
    meta = validate_metadata(data)

    # Dataclass frozen
    with pytest.raises(FrozenInstanceError):
        meta.title = "New"

    # Tuple mutability
    with pytest.raises(AttributeError):
        meta.related_goals.append("g2")  # type: ignore

    # MappingProxyType mutability
    with pytest.raises(TypeError):
        meta.extensions["nested"] = "new"  # type: ignore

    with pytest.raises(TypeError):
        meta.extensions["nested"]["list"][0] = 99  # type: ignore


def test_deterministic_serialization():
    data = {
        "id": "prop-20260712T184129Z-a1b2c3d4",
        "schema_version": 1,
        "patch_schema_version": 1,
        "lifecycle_schema_version": None,
        "title": "T",
        "description": "D",
        "status": "draft",
        "risk": "low",
        "created_at": "2026-07-12T18:41:29Z",
        "created_by": "system",
        "submitted_at": None,
        "submitted_by": None,
        "review_digest": None,
        "approved_at": None,
        "approved_by": None,
        "rejected_at": None,
        "rejected_by": None,
        "rejection_reason": None,
        "applied_at": None,
        "applied_by": None,
        "related_goals": ["g1"],
        "related_sources": [],
        "extensions": {"z": 1, "a": 2, "nested": {"c": 3, "b": 4}},
    }
    meta = validate_metadata(data)
    serialized = serialize_metadata(meta)

    # Should convert tuples back to lists, and MappingProxyType back to dict
    assert isinstance(serialized["related_goals"], list)
    assert isinstance(serialized["extensions"], dict)

    # Should be exactly equal to input data structurally
    assert serialized == data

    # Keys should be sorted in extensions recursively
    ext_keys = list(serialized["extensions"].keys())
    assert ext_keys == ["a", "nested", "z"]
    nested_keys = list(serialized["extensions"]["nested"].keys())
    assert nested_keys == ["b", "c"]

    # JSON serialization should not fail
    assert json.dumps(serialized)


def test_non_empty_strings():
    base = {
        "id": "prop-20260712T184129Z-a1b2c3d4",
        "schema_version": 1,
        "patch_schema_version": 1,
        "title": "   ",  # empty
        "description": "D",
        "status": "draft",
        "risk": "low",
        "created_at": "2026-07-12T18:41:29Z",
        "created_by": "system",
    }
    with pytest.raises(ProposalSchemaError) as exc:
        validate_metadata(base)
    assert exc.value.code == "empty_string"
    assert exc.value.field_path == "title"


def test_generate_proposal_id():
    def mock_clock():
        return datetime(2026, 7, 12, 18, 41, 29, tzinfo=timezone.utc)

    def mock_random():
        return "a1b2c3d4"

    pid = generate_proposal_id(mock_clock, mock_random)
    assert pid == "prop-20260712T184129Z-a1b2c3d4"

    # Test non-UTC rejection
    def mock_bad_clock():
        return datetime(2026, 7, 12, 18, 41, 29, tzinfo=timezone(timedelta(hours=1)))

    with pytest.raises(ValueError, match="UTC datetime"):
        generate_proposal_id(mock_bad_clock, mock_random)

    # Test bad suffix length
    def mock_bad_random():
        return "abc"

    with pytest.raises(ValueError, match="8 lowercase"):
        generate_proposal_id(mock_clock, mock_bad_random)
