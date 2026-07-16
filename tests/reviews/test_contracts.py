from datetime import date

import pytest

from lifeos.reviews.contracts import (
    REVIEW_SCHEMA_VERSION,
    ReviewContractError,
    default_phases,
    review_identity,
    review_path,
    stable_fingerprint,
    validate_review_metadata,
)


def metadata(kind: str = "daily", day: date = date(2026, 7, 16)) -> dict[str, object]:
    review_id, start, end = review_identity(kind, day)  # type: ignore[arg-type]
    return {
        "review_schema": REVIEW_SCHEMA_VERSION,
        "review_id": review_id,
        "review_kind": kind,
        "period_start": start,
        "period_end": end,
        "timezone": "Europe/Istanbul",
        "status": "open",
        "created_at": "2026-07-16T09:00:00+03:00",
        "updated_at": "2026-07-16T09:00:00+03:00",
        "phases": [phase.to_dict() for phase in default_phases(kind)],  # type: ignore[arg-type]
        "item_decisions": [],
        "answers": [],
        "proposal_refs": [],
        "migrated_from": [],
        "snapshot_history": [],
        "lifecycle_events": [],
    }


def test_daily_and_weekly_identity_paths_cover_year_boundary() -> None:
    assert review_identity("daily", date(2026, 7, 16))[0] == "daily-2026-07-16"
    assert review_path("daily", date(2026, 7, 16)) == "reviews/daily/2026-07-16.md"
    review_id, start, end = review_identity("weekly", date(2026, 1, 1))
    assert (review_id, start.isoformat(), end.isoformat()) == ("weekly-2026-W01", "2025-12-29", "2026-01-04")
    assert review_path("weekly", date(2026, 1, 1)) == "reviews/weekly/2026-W01.md"


def test_metadata_round_trip_preserves_unknown_as_absent() -> None:
    parsed = validate_review_metadata(metadata(), path="reviews/daily/2026-07-16.md")
    assert parsed.review_id == "daily-2026-07-16"
    assert parsed.current_phase is None
    assert parsed.item_decisions == ()
    assert tuple(phase.phase_id for phase in parsed.phases) == ("morning", "evening")


def test_metadata_rejects_unsupported_schema_identity_and_duplicate_decisions() -> None:
    raw = metadata()
    raw["review_schema"] = 99
    with pytest.raises(ReviewContractError, match="unsupported") as unsupported:
        validate_review_metadata(raw)
    assert unsupported.value.code == "unsupported_schema"

    raw = metadata()
    raw["review_id"] = "daily-2026-07-15"
    with pytest.raises(ReviewContractError) as mismatch:
        validate_review_metadata(raw)
    assert mismatch.value.code == "identity_mismatch"

    raw = metadata()
    decision = {
        "item_id": "attention:item",
        "evidence_fingerprint": stable_fingerprint("evidence"),
        "decision": "carry",
        "decided_at": "2026-07-16T10:00:00+03:00",
    }
    raw["item_decisions"] = [decision, decision]
    with pytest.raises(ReviewContractError) as duplicate:
        validate_review_metadata(raw)
    assert duplicate.value.code == "duplicate_decision"


def test_phase_progress_rejects_conflicting_section_state() -> None:
    raw = metadata()
    phases = raw["phases"]
    assert isinstance(phases, list)
    first = phases[0]
    assert isinstance(first, dict)
    first["completed_sections"] = ["plans"]
    first["skipped_sections"] = ["plans"]
    with pytest.raises(ReviewContractError) as conflict:
        validate_review_metadata(raw)
    assert conflict.value.code == "conflicting_progress"
