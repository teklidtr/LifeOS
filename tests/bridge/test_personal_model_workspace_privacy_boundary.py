from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from lifeos.bridge.personal_model_workspace import PersonalModelWorkspaceBridge
from lifeos.bridge.protocol import ProtocolError
from lifeos.patterns import (
    PatternMetadata,
    PatternOrigin,
    compute_evidence_fingerprint,
    serialize_pattern,
)
from lifeos.patterns.proposals import PatternProposalRequest

NOW_TEXT = "2026-09-04T12:00:00+00:00"


def _metadata(
    pattern_id: str,
    *,
    origin: PatternOrigin | None = None,
    statement: str | None = None,
) -> PatternMetadata:
    return PatternMetadata(
        pattern_id=pattern_id,
        title=pattern_id.replace("-", " ").title(),
        description=f"Description for {pattern_id}.",
        status="seed",
        confidence="medium",
        review_reasons=(),
        statement=statement or f"Statement for {pattern_id}.",
        origin=origin or PatternOrigin("manual"),
        created_at="2026-09-01T09:00:00Z",
        updated_at="2026-09-02T09:00:00Z",
        evidence_fingerprint=compute_evidence_fingerprint(()),
        evidence=(),
    )


def _write_pattern(vault: Path, name: str, metadata: PatternMetadata) -> Path:
    path = vault / "patterns" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_pattern(metadata), encoding="utf-8")
    return path


def _write_policy(vault: Path) -> None:
    path = vault / "system" / "retrieval-policy.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "schema_version: 1\nprotected_prefixes:\n  - reviews/private\n",
        encoding="utf-8",
    )


def _bridge(tmp_path: Path) -> tuple[PersonalModelWorkspaceBridge, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    return (
        PersonalModelWorkspaceBridge(
            vault_root=vault,
            runtime_dir=tmp_path / "runtime",
            actor_id="obsidian-local",
        ),
        vault,
    )


def test_protected_origin_subpath_is_redacted_and_cannot_enter_proposal(
    tmp_path: Path,
) -> None:
    bridge, vault = _bridge(tmp_path)
    _write_policy(vault)
    _write_pattern(
        vault,
        "seed.md",
        _metadata(
            "pattern-seed",
            origin=PatternOrigin("manual", source_ref="reviews/private/secret.md#Decision"),
        ),
    )

    workspace = bridge.dispatch("personal-model.rebuild", {"now": NOW_TEXT})
    item = workspace["groups"]["seeds"][0]

    assert item["origin"] == {"kind": "manual", "source_ref": None}
    assert item["related_paths"] == []

    with pytest.raises(ProtocolError) as denied:
        bridge.dispatch(
            "personal-model.proposal.preview",
            {
                "action": "adopt",
                "target_path": item["pattern_path"],
                "expected_target_hash": item["pattern_content_hash"],
                "transition_reason": "Do not disclose a protected origin subpath.",
                "now": NOW_TEXT,
            },
        )

    assert denied.value.code == "authorization_denied"
    assert denied.value.data == {"path": "reviews/private/secret.md"}
    assert not (vault / "proposals").exists()


def test_service_read_revalidates_inspected_hash_after_bridge_precheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge, vault = _bridge(tmp_path)
    pattern = _write_pattern(vault, "seed.md", _metadata("pattern-seed"))
    workspace = bridge.dispatch("personal-model.rebuild", {"now": NOW_TEXT})
    item = workspace["groups"]["seeds"][0]
    original_check = bridge._check_expected_target
    changed = replace(
        _metadata("pattern-seed"),
        statement="Changed after the bridge precheck but before proposal construction.",
    )

    def mutate_after_check(
        request: PatternProposalRequest,
        expected_hash: str | None,
        *,
        allow_path: Callable[[str], bool],
    ) -> None:
        original_check(request, expected_hash, allow_path=allow_path)
        pattern.write_text(serialize_pattern(changed), encoding="utf-8")

    monkeypatch.setattr(bridge, "_check_expected_target", mutate_after_check)

    with pytest.raises(ProtocolError) as stale:
        bridge.dispatch(
            "personal-model.proposal.preview",
            {
                "action": "adopt",
                "target_path": item["pattern_path"],
                "expected_target_hash": item["pattern_content_hash"],
                "transition_reason": "Bind this decision to the bytes I inspected.",
                "now": NOW_TEXT,
            },
        )

    assert stale.value.code == "stale_target"
    assert stale.value.data["expected_hash"] == item["pattern_content_hash"]
    assert stale.value.data["current_hash"] != item["pattern_content_hash"]
    assert not (vault / "proposals").exists()
