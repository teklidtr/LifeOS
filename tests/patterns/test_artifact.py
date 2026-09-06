from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from lifeos.patterns import (
    PatternArtifactService,
    PatternError,
    PatternEvaluation,
    PatternEvidence,
    PatternMetadata,
    PatternOrigin,
    PatternStatus,
    parse_pattern,
    serialize_pattern,
)

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
FINGERPRINT = "sha256:" + "f" * 64


def metadata(*, status: PatternStatus = "seed") -> PatternMetadata:
    return PatternMetadata(
        pattern_id="pattern-focus-after-walk",
        title="Focus after walking",
        description="Morning walking may be associated with better focus.",
        status=status,
        confidence="medium",
        review_reasons=(),
        statement=(
            "On otherwise similar mornings, walking before study tends to precede higher focus."
        ),
        origin=PatternOrigin("manual"),
        created_at="2026-09-03T10:00:00Z",
        updated_at="2026-09-03T10:00:00Z",
        evidence_fingerprint=FINGERPRINT,
        evidence=(
            PatternEvidence(
                path="journal/2026-09-01.md",
                source_id="journal-2026-09-01",
                content_hash=HASH_A,
                role="supporting",
                observation_id="obs-focus-1",
            ),
            PatternEvidence(
                path="journal/2026-09-02.md",
                content_hash=HASH_B,
                role="contesting",
                event_id="event-study-2",
            ),
        ),
        evaluation=PatternEvaluation(
            "metric-association",
            {"minimum_samples": 5, "metrics": {"outcome": "focus", "input": "walk"}},
        ),
    )


def write_pattern(root: Path, name: str, item: PatternMetadata) -> Path:
    path = root / "patterns" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        serialize_pattern(
            item,
            body_prefix="\n# Working hypothesis\n\nHuman context before the summary.  \n\n",
            body_suffix="\n\n## Reflection\n\nKeep this exactly.  \n",
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("status", ["seed", "active", "needs-review", "archived"])
def test_canonical_patterns_round_trip_all_lifecycle_states(
    tmp_path: Path, status: PatternStatus
) -> None:
    item = metadata(status=status)
    path = write_pattern(tmp_path, f"{status}.md", item)
    content = path.read_text(encoding="utf-8")

    parsed = parse_pattern(path, f"patterns/{status}.md", content)

    assert parsed is not None
    assert parsed.metadata.status == status
    assert parsed.metadata.evidence[1].role == "contesting"
    assert "- Contesting: 1" in content
    assert (
        serialize_pattern(
            parsed.metadata,
            body_prefix=parsed.body_prefix,
            body_suffix=parsed.body_suffix,
        )
        == content
    )


def test_human_owned_content_is_preserved_around_managed_summary(tmp_path: Path) -> None:
    prefix = (
        "\r\n# Working hypothesis\r\n\r\n"
        "```md\r\n<!-- lifeos:managed:start personal-pattern-evidence -->\r\n```\r\n"
        "Human prefix with spaces.  \r\n\r\n"
    )
    suffix = "\r\n\r\n## Reflection\r\n\r\nHuman suffix with spaces.  \r\n\r\n"
    content = serialize_pattern(metadata(), body_prefix=prefix, body_suffix=suffix)
    path = tmp_path / "patterns" / "preserve.md"
    parsed = parse_pattern(path, "patterns/preserve.md", content)

    assert parsed is not None
    assert parsed.body_prefix.encode() == prefix.encode()
    assert parsed.body_suffix.encode() == suffix.encode()
    assert parsed.human_body.encode() == (prefix + suffix).encode()
    assert (
        serialize_pattern(
            parsed.metadata,
            body_prefix=parsed.body_prefix,
            body_suffix=parsed.body_suffix,
        ).encode()
        == content.encode()
    )


def test_unrecognized_markdown_remains_ordinary_user_content(tmp_path: Path) -> None:
    ordinary = tmp_path / "patterns" / "notes.md"
    ordinary.parent.mkdir(parents=True)
    ordinary.write_text("---\ntype: pattern\n---\n\nJust a note.\n", encoding="utf-8")
    canonical = write_pattern(tmp_path, "canonical.md", metadata())

    assert parse_pattern(ordinary, "patterns/notes.md", ordinary.read_text()) is None
    listed = PatternArtifactService(vault_root=tmp_path).list()
    assert [item.path for item in listed] == ["patterns/canonical.md"]
    assert canonical.exists()


def test_duplicate_pattern_ids_fail_closed(tmp_path: Path) -> None:
    item = metadata()
    write_pattern(tmp_path, "one.md", item)
    write_pattern(tmp_path, "two.md", replace(item, title="Same identity, another file"))

    with pytest.raises(PatternError) as error:
        PatternArtifactService(vault_root=tmp_path).list()
    assert error.value.code == "duplicate_identity"


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        (HASH_A, "sha256:ABC", "invalid_hash"),
        ("journal/2026-09-01.md", "../outside.md", "invalid_evidence_path"),
        (FINGERPRINT, "sha256:not-a-digest", "invalid_hash"),
    ],
)
def test_malformed_hashes_and_paths_have_typed_diagnostics(
    tmp_path: Path, old: str, new: str, code: str
) -> None:
    content = serialize_pattern(metadata()).replace(old, new, 1)

    with pytest.raises(PatternError) as error:
        parse_pattern(tmp_path / "patterns/bad.md", "patterns/bad.md", content)
    assert error.value.code == code


def test_unsupported_schema_and_declared_malformed_pattern_fail_typed(tmp_path: Path) -> None:
    future = serialize_pattern(metadata()).replace("pattern_schema: 1", "pattern_schema: 99", 1)
    with pytest.raises(PatternError) as schema:
        parse_pattern(tmp_path / "patterns/future.md", "patterns/future.md", future)
    assert schema.value.code == "unsupported_schema"

    malformed = "---\npattern_schema: 1\ntype: pattern\nevidence: [\n"
    with pytest.raises(PatternError) as invalid:
        parse_pattern(tmp_path / "patterns/broken.md", "patterns/broken.md", malformed)
    assert invalid.value.code == "malformed_artifact"


def test_evaluation_parameters_serialize_in_stable_key_order() -> None:
    first = replace(
        metadata(),
        evaluation=PatternEvaluation("metric-association", {"z": 1, "a": {"y": 2, "b": 3}}),
    )
    second = replace(
        metadata(),
        evaluation=PatternEvaluation("metric-association", {"a": {"b": 3, "y": 2}, "z": 1}),
    )

    assert serialize_pattern(first) == serialize_pattern(second)
