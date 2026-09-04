from __future__ import annotations

from dataclasses import replace

from lifeos.patterns import PatternMetadata, PatternOrigin, serialize_pattern
from lifeos.proposals.human_patch_policy import allows_canonical_pattern_managed_patch

FINGERPRINT = "sha256:" + "f" * 64


def _pattern() -> PatternMetadata:
    return PatternMetadata(
        pattern_id="pattern-focus-after-walk",
        title="Focus after walking",
        description="Walking may be associated with better focus.",
        status="seed",
        confidence="medium",
        review_reasons=(),
        statement="Walking before study may precede better focus.",
        origin=PatternOrigin("manual"),
        created_at="2026-09-04T04:00:00Z",
        updated_at="2026-09-04T04:00:00Z",
        evidence_fingerprint=FINGERPRINT,
        evidence=(),
    )


def test_canonical_identity_stable_pattern_patch_may_update_managed_summary() -> None:
    original = serialize_pattern(_pattern(), body_prefix="\n# Context\n\n", body_suffix="\n")
    candidate = serialize_pattern(
        replace(
            _pattern(),
            status="active",
            updated_at="2026-09-04T05:00:00Z",
            last_reviewed_at="2026-09-04T05:00:00Z",
        ),
        body_prefix="\n# Context\n\n",
        body_suffix="\n",
    )

    assert allows_canonical_pattern_managed_patch(
        target_path="patterns/focus-after-walk.md",
        original_text=original,
        candidate_text=candidate,
    )


def test_pattern_patch_rejects_identity_change_and_noncanonical_managed_summary() -> None:
    original = serialize_pattern(_pattern())
    changed_id = serialize_pattern(replace(_pattern(), pattern_id="pattern-other"))
    tampered_summary = serialize_pattern(replace(_pattern(), status="active")).replace(
        "- Supporting: 0",
        "- Supporting: 99",
        1,
    )

    assert not allows_canonical_pattern_managed_patch(
        target_path="patterns/focus-after-walk.md",
        original_text=original,
        candidate_text=changed_id,
    )
    assert not allows_canonical_pattern_managed_patch(
        target_path="patterns/focus-after-walk.md",
        original_text=original,
        candidate_text=tampered_summary,
    )


def test_generic_managed_markdown_remains_outside_pattern_exception() -> None:
    ordinary = (
        "# Note\n\n"
        "<!-- lifeos:managed:start summary -->\n"
        "Old\n"
        "<!-- lifeos:managed:end summary -->\n"
    )
    candidate = ordinary.replace("Old", "New")

    assert not allows_canonical_pattern_managed_patch(
        target_path="wiki/note.md",
        original_text=ordinary,
        candidate_text=candidate,
    )
