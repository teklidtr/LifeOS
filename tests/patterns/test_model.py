from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from lifeos.patterns import (
    PatternEvaluation,
    PatternEvidence,
    PatternMetadata,
    PatternOrigin,
    PatternStatus,
    PersonalModelService,
    build_personal_model_document,
    compute_evidence_fingerprint,
    serialize_pattern,
    serialize_personal_model,
)
from lifeos.registry import Registry, register_scan
from lifeos.scanner import scan_vault

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _allow_all(_path: str) -> bool:
    return True


def _digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _registry(tmp_path: Path) -> Registry:
    registry = Registry(tmp_path / "runtime" / "registry.db")
    registry.initialize()
    return registry


def _metadata(
    pattern_id: str,
    *,
    status: PatternStatus = "seed",
    evidence: tuple[PatternEvidence, ...] = (),
    evaluation: PatternEvaluation | None = None,
    review_due_at: str | None = None,
) -> PatternMetadata:
    return PatternMetadata(
        pattern_id=pattern_id,
        title=pattern_id.replace("-", " ").title(),
        description=f"Derived description for {pattern_id}.",
        status=status,
        confidence="medium",
        review_reasons=("Existing reviewed reason.",) if status == "needs-review" else (),
        statement=f"Canonical statement for {pattern_id}.",
        origin=PatternOrigin("manual", source_ref="journal/source.md"),
        created_at="2026-09-01T09:00:00Z",
        updated_at="2026-09-02T09:00:00Z",
        last_reviewed_at="2026-09-02T09:00:00Z",
        review_due_at=review_due_at,
        evidence_fingerprint=compute_evidence_fingerprint(evidence),
        evidence=evidence,
        evaluation=evaluation,
    )


def _write_pattern(vault: Path, name: str, metadata: PatternMetadata) -> Path:
    path = vault / "patterns" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_pattern(metadata), encoding="utf-8")
    return path


def _write(vault: Path, relative_path: str, content: str) -> Path:
    path = vault / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_empty_personal_model_is_a_valid_rebuildable_document(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    registry = _registry(tmp_path)

    document = build_personal_model_document(
        vault_root=vault,
        registry=registry,
        allow_path=_allow_all,
        now=NOW,
    )

    assert document.items == ()
    assert document.diagnostics == ()
    assert document.source_hash.startswith("sha256:")


def test_mixed_statuses_are_grouped_and_ordered_by_stable_identity(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_pattern(vault, "z-seed.md", _metadata("pattern-z", status="seed"))
    _write_pattern(vault, "b-active.md", _metadata("pattern-b", status="active"))
    _write_pattern(vault, "a-active.md", _metadata("pattern-a", status="active"))
    _write_pattern(
        vault,
        "review.md",
        _metadata(
            "pattern-review",
            status="needs-review",
            review_due_at="2026-09-03T09:00:00Z",
        ),
    )
    _write_pattern(vault, "archive.md", _metadata("pattern-archive", status="archived"))
    registry = _registry(tmp_path)

    document = build_personal_model_document(
        vault_root=vault,
        registry=registry,
        allow_path=_allow_all,
        now=NOW,
    )

    assert [item.pattern_id for item in document.active] == ["pattern-a", "pattern-b"]
    assert [item.pattern_id for item in document.seeds] == ["pattern-z"]
    assert [item.pattern_id for item in document.needs_review] == ["pattern-review"]
    assert [item.pattern_id for item in document.archived] == ["pattern-archive"]
    assert document.needs_review[0].review_due is True
    assert document.needs_review[0].review_reasons == ("Existing reviewed reason.",)
    assert all(item.evidence_health == "none" for item in document.items)
    assert all(item.pattern_content_hash.startswith("sha256:") for item in document.items)


def test_malformed_pattern_surfaces_diagnostic_without_hiding_valid_items(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_pattern(vault, "valid.md", _metadata("pattern-valid"))
    _write(
        vault,
        "patterns/broken.md",
        "---\npattern_schema: 1\ntype: pattern\nevidence: [\n",
    )
    registry = _registry(tmp_path)

    document = build_personal_model_document(
        vault_root=vault,
        registry=registry,
        allow_path=_allow_all,
        now=NOW,
    )

    assert [item.pattern_id for item in document.seeds] == ["pattern-valid"]
    assert [(item.source_path, item.code) for item in document.diagnostics] == [
        ("patterns/broken.md", "malformed_artifact")
    ]


def test_duplicate_ids_are_diagnostics_not_healthy_model_items(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    metadata = _metadata("pattern-duplicate")
    _write_pattern(vault, "one.md", metadata)
    _write_pattern(vault, "two.md", replace(metadata, title="Duplicate identity"))
    registry = _registry(tmp_path)

    document = build_personal_model_document(
        vault_root=vault,
        registry=registry,
        allow_path=_allow_all,
        now=NOW,
    )

    assert document.items == ()
    assert [(item.source_path, item.code) for item in document.diagnostics] == [
        ("patterns/one.md", "duplicate_identity"),
        ("patterns/two.md", "duplicate_identity"),
    ]


def test_changed_evidence_is_visible_without_advancing_reviewed_reference(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    before = "---\nid: source-one\ntype: note\ntitle: Source\n---\nbefore\n"
    source = _write(vault, "journal/source.md", before)
    evidence = (
        PatternEvidence(
            path="journal/source.md",
            source_id="source-one",
            content_hash=_digest(before),
            role="supporting",
        ),
    )
    _write_pattern(vault, "tracked.md", _metadata("pattern-tracked", evidence=evidence))
    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    after = before.replace("before", "after")
    source.write_text(after, encoding="utf-8")
    register_scan(registry, vault, scan_vault(vault))

    document = build_personal_model_document(
        vault_root=vault,
        registry=registry,
        allow_path=_allow_all,
        now=NOW,
    )
    item = document.seeds[0]

    assert item.evidence_health == "attention"
    assert item.evidence_diagnostics[0].state == "changed"
    assert item.evidence_diagnostics[0].reference.content_hash == _digest(before)
    assert item.evidence_diagnostics[0].current_content_hash == _digest(after)
    assert item.review_recommendation == "review"
    assert "changed-evidence" in {reason.code for reason in item.review_trigger_reasons}


def test_supported_recipe_reuses_observation_freshness(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    for day in range(1, 6):
        _write(
            vault,
            f"journal/2026-09-0{day}.md",
            (
                "---\n"
                f"date: 2026-09-0{day}\n"
                "metrics:\n"
                f"  sleep_hours: {day}\n"
                f"  morning_energy: {day * 2}\n"
                "---\n"
            ),
        )
    evaluation = PatternEvaluation(
        "numeric-metric-association",
        {"outcome": "morning_energy", "factor": "sleep_hours"},
    )
    _write_pattern(
        vault,
        "freshness.md",
        _metadata("pattern-freshness", evaluation=evaluation),
    )
    registry = _registry(tmp_path)

    document = build_personal_model_document(
        vault_root=vault,
        registry=registry,
        allow_path=_allow_all,
        now=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
    )
    item = document.seeds[0]

    assert item.freshness_days == 0
    assert item.review_recommendation == "review"
    assert "materially-new-evidence" in {reason.code for reason in item.review_trigger_reasons}


def test_delete_and_rebuild_recreates_identical_disposable_generation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_pattern(vault, "stable.md", _metadata("pattern-stable", status="active"))
    registry = _registry(tmp_path)
    service = PersonalModelService(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        registry=registry,
        allow_path=_allow_all,
    )

    first = service.rebuild(now=NOW)
    first_active = service.active_path()
    assert first_active is not None
    first_bytes = (first_active / "model.json").read_bytes()
    assert json.loads(first_bytes)["active"][0]["pattern_id"] == "pattern-stable"

    shutil.rmtree(service.root)
    assert service.active_path() is None

    second = service.rebuild(now=NOW)
    second_active = service.active_path()
    assert second_active is not None
    second_bytes = (second_active / "model.json").read_bytes()

    assert first == second
    assert first_bytes == second_bytes == serialize_personal_model(second)
    assert not (vault / "profile" / "personal-model.md").exists()
