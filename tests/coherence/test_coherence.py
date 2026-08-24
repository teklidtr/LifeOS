from __future__ import annotations

import hashlib
from pathlib import Path

from lifeos.coherence import (
    assess_proposal_target,
    collect_identity_snapshot,
    describe_topology,
)
from lifeos.config import LifeOSConfig


def _note(stable_id: str | None, body: str = "Body\n") -> str:
    identifier = f"id: {stable_id}\n" if stable_id is not None else ""
    return f"---\n{identifier}type: wiki\ntitle: Example\n---\n{body}"


def _hash(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def test_identity_snapshot_distinguishes_id_path_and_content_version(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    content = _note("wiki-example")
    original = vault / "wiki" / "old-name.md"
    original.write_text(content, encoding="utf-8")

    before = collect_identity_snapshot(vault)
    original.rename(vault / "wiki" / "new-name.md")
    after = collect_identity_snapshot(vault)

    assert before.healthy is True
    assert after.healthy is True
    assert before.notes[0].stable_id == after.notes[0].stable_id == "wiki-example"
    assert before.notes[0].path == "wiki/old-name.md"
    assert after.notes[0].path == "wiki/new-name.md"
    assert before.notes[0].content_hash == after.notes[0].content_hash == _hash(content)
    assert after.notes[0].relocation_safe is True


def test_duplicate_stable_ids_fail_closed_in_snapshot(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "wiki" / "a.md").write_text(_note("duplicate"), encoding="utf-8")
    (vault / "wiki" / "b.md").write_text(_note("duplicate"), encoding="utf-8")

    snapshot = collect_identity_snapshot(vault)

    assert snapshot.healthy is False
    assert snapshot.by_stable_id("duplicate")[0].path == "wiki/a.md"
    assert len(snapshot.by_stable_id("duplicate")) == 2
    assert any(item.code == "stable-id-ambiguous" for item in snapshot.diagnostics)


def test_legacy_wiki_note_remains_path_addressable_but_warns(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "wiki" / "legacy.md").write_text(_note(None), encoding="utf-8")

    snapshot = collect_identity_snapshot(vault)

    assert snapshot.healthy is True
    assert snapshot.notes[0].stable_id is None
    assert snapshot.notes[0].relocation_safe is False
    assert any(item.code == "stable-id-missing" for item in snapshot.diagnostics)


def test_approved_proposal_relocation_requires_renewed_review(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    content = _note("wiki-example")
    (vault / "wiki" / "renamed.md").write_text(content, encoding="utf-8")
    snapshot = collect_identity_snapshot(vault)

    result = assess_proposal_target(
        snapshot,
        reviewed_path="wiki/original.md",
        reviewed_base_hash=_hash(content),
        stable_id="wiki-example",
        proposal_status="approved",
    )

    assert result.state == "relocated-review-required"
    assert result.current_path == "wiki/renamed.md"
    assert result.may_apply_without_new_review is False
    assert result.draft_rebase_allowed is False
    assert result.requires_path_revalidation is True


def test_draft_relocation_can_only_rebase_with_new_review_snapshot(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    content = _note("wiki-example")
    (vault / "wiki" / "renamed.md").write_text(content, encoding="utf-8")
    snapshot = collect_identity_snapshot(vault)

    result = assess_proposal_target(
        snapshot,
        reviewed_path="wiki/original.md",
        reviewed_base_hash=_hash(content),
        stable_id="wiki-example",
        proposal_status="draft",
    )

    assert result.state == "relocated-draft-rebase-required"
    assert result.draft_rebase_allowed is True
    assert result.may_apply_without_new_review is False
    assert result.requires_path_revalidation is True


def test_same_stable_id_with_changed_content_remains_stale(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    reviewed = _note("wiki-example", "Reviewed\n")
    changed = _note("wiki-example", "Synchronized edit\n")
    (vault / "wiki" / "renamed.md").write_text(changed, encoding="utf-8")
    snapshot = collect_identity_snapshot(vault)

    result = assess_proposal_target(
        snapshot,
        reviewed_path="wiki/original.md",
        reviewed_base_hash=_hash(reviewed),
        stable_id="wiki-example",
        proposal_status="approved",
    )

    assert result.state == "stale-content"
    assert result.current_path == "wiki/renamed.md"
    assert result.may_apply_without_new_review is False


def test_identity_change_at_reviewed_path_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    content = _note("replacement-id")
    (vault / "wiki" / "target.md").write_text(content, encoding="utf-8")
    snapshot = collect_identity_snapshot(vault)

    result = assess_proposal_target(
        snapshot,
        reviewed_path="wiki/target.md",
        reviewed_base_hash=_hash(content),
        stable_id="expected-id",
        proposal_status="approved",
    )

    assert result.state == "identity-changed"
    assert result.may_apply_without_new_review is False


def test_topology_keeps_sync_transport_outside_core(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    inside = describe_topology(LifeOSConfig(vault, vault / ".lifeos"))
    outside = describe_topology(LifeOSConfig(vault, tmp_path / "runtime"))

    assert inside.writer_model == "single-active-lifeos-writer"
    assert inside.runtime_location == "inside-canonical-vault"
    assert ".lifeos/" in inside.required_sync_exclusions
    assert inside.sync_transport_owner == "external"
    assert outside.runtime_location == "node-local-outside-vault"
    assert ".lifeos/" not in outside.required_sync_exclusions


def test_topology_excludes_configured_runtime_path_inside_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    topology = describe_topology(LifeOSConfig(vault, vault / "runtime" / "node-a"))

    assert topology.runtime_location == "inside-canonical-vault"
    assert topology.required_sync_exclusions[0] == "runtime/node-a/"
    assert ".lifeos/" not in topology.required_sync_exclusions
