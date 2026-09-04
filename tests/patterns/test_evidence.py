from __future__ import annotations

import hashlib
from pathlib import Path

from lifeos.patterns import (
    PatternEvidence,
    compute_evidence_fingerprint,
    normalize_evidence_reference,
    resolve_evidence_states,
)
from lifeos.registry import Registry, register_scan
from lifeos.scanner import scan_vault

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _note(stable_id: str, body: str) -> str:
    return f"---\nid: {stable_id}\ntype: wiki\ntitle: Evidence\n---\n{body}\n"


def _digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _write(vault: Path, relative_path: str, content: str) -> Path:
    path = vault / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _registry(tmp_path: Path) -> Registry:
    registry = Registry(tmp_path / "runtime" / "registry.db")
    registry.initialize()
    return registry


def test_fingerprint_is_normalized_order_independent_and_deduplicated() -> None:
    supporting = PatternEvidence(
        path="journal/a.md",
        source_id="source-a",
        content_hash=HASH_A,
        role="supporting",
        observation_id="obs-1",
    )
    contesting = PatternEvidence(
        path="journal/b.md",
        content_hash=HASH_B,
        role="contesting",
        event_id="event-2",
    )

    normalized = normalize_evidence_reference(supporting)
    assert normalized.canonical_tuple() == (
        "supporting",
        "source-a",
        "journal/a.md",
        HASH_A,
        "obs-1",
        None,
    )
    expected = "sha256:95b04ef0066c5f5a52647eacda1c997d7389084b05f62c3d417655e0b78c1b4b"
    assert compute_evidence_fingerprint((supporting, contesting, supporting)) == expected
    assert compute_evidence_fingerprint((contesting, supporting)) == expected


def test_evidence_role_remains_part_of_the_fingerprint() -> None:
    supporting = PatternEvidence("journal/a.md", HASH_A, "supporting")
    contesting = PatternEvidence("journal/a.md", HASH_A, "contesting")

    assert compute_evidence_fingerprint((supporting,)) != compute_evidence_fingerprint(
        (contesting,)
    )


def test_registry_resolution_distinguishes_all_evidence_states(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    unchanged_text = _note("unchanged-id", "unchanged")
    moved_text = _note("moved-id", "moved")
    changed_before = _note("changed-id", "before")
    deleted_text = _note("deleted-id", "deleted")
    ambiguous_a = _note("ambiguous-id", "a")
    ambiguous_b = _note("other-id", "b")

    _write(vault, "journal/unchanged.md", unchanged_text)
    moved = _write(vault, "journal/moved-old.md", moved_text)
    changed = _write(vault, "journal/changed.md", changed_before)
    deleted = _write(vault, "journal/deleted.md", deleted_text)
    _write(vault, "journal/ambiguous-a.md", ambiguous_a)
    _write(vault, "journal/ambiguous-b.md", ambiguous_b)

    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    moved.rename(vault / "journal" / "moved-new.md")
    changed_after = _note("changed-id", "after")
    changed.write_text(changed_after, encoding="utf-8")
    deleted.unlink()
    register_scan(registry, vault, scan_vault(vault))

    with registry.connect() as connection:
        connection.execute(
            "UPDATE files SET stable_id = 'ambiguous-id' WHERE vault_path = 'journal/ambiguous-b.md'"
        )
        connection.commit()

    references = (
        PatternEvidence(
            "journal/unchanged.md",
            _digest(unchanged_text),
            "supporting",
            source_id="unchanged-id",
        ),
        PatternEvidence(
            "journal/moved-old.md",
            _digest(moved_text),
            "supporting",
            source_id="moved-id",
        ),
        PatternEvidence(
            "journal/changed.md",
            _digest(changed_before),
            "contesting",
            source_id="changed-id",
        ),
        PatternEvidence(
            "journal/deleted.md",
            _digest(deleted_text),
            "contextual",
            source_id="deleted-id",
        ),
        PatternEvidence(
            "journal/ambiguous-a.md",
            _digest(ambiguous_a),
            "supporting",
            source_id="ambiguous-id",
        ),
        PatternEvidence(
            "journal/missing.md",
            HASH_A,
            "contextual",
            source_id="missing-id",
        ),
    )

    diagnostics = resolve_evidence_states(registry, references)

    assert [item.state for item in diagnostics] == [
        "unchanged",
        "moved",
        "changed",
        "deleted",
        "ambiguous",
        "missing",
    ]
    assert diagnostics[1].current_path == "journal/moved-new.md"
    assert diagnostics[1].current_content_hash == references[1].content_hash
    assert diagnostics[2].reference.content_hash == _digest(changed_before)
    assert diagnostics[2].current_content_hash == _digest(changed_after)
    assert diagnostics[3].candidate_paths == ("journal/deleted.md",)
    assert diagnostics[4].candidate_paths == (
        "journal/ambiguous-a.md",
        "journal/ambiguous-b.md",
    )
    assert diagnostics[5].current_path is None


def test_relocated_and_modified_stable_source_is_changed_not_moved(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    original_text = _note("source-id", "before")
    source = _write(vault, "journal/old.md", original_text)
    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    source.unlink()
    changed_text = _note("source-id", "after")
    _write(vault, "journal/new.md", changed_text)
    register_scan(registry, vault, scan_vault(vault))

    reference = PatternEvidence(
        "journal/old.md",
        _digest(original_text),
        "supporting",
        source_id="source-id",
    )
    diagnostic = resolve_evidence_states(registry, (reference,))[0]

    assert diagnostic.state == "changed"
    assert diagnostic.current_path == "journal/new.md"
    assert diagnostic.reference.path == "journal/old.md"
    assert diagnostic.reference.content_hash == _digest(original_text)
    assert diagnostic.current_content_hash == _digest(changed_text)


def test_path_only_reference_uses_path_without_inventing_stable_identity(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    content = _note("available-id", "body")
    _write(vault, "journal/path-only.md", content)
    registry = _registry(tmp_path)
    register_scan(registry, vault, scan_vault(vault))

    reference = PatternEvidence(
        "journal/path-only.md",
        _digest(content),
        "contextual",
    )
    diagnostic = resolve_evidence_states(registry, (reference,))[0]

    assert diagnostic.state == "unchanged"
    assert diagnostic.reference.source_id is None
    assert diagnostic.current_path == "journal/path-only.md"
