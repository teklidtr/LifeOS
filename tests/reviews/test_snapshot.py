from datetime import date, datetime, timezone
from pathlib import Path

from lifeos.reviews import ReviewArtifactService
from lifeos.reviews.snapshot import build_review_snapshot, refresh_review_snapshot, render_snapshot_items

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_snapshot_has_source_hashes_fingerprints_and_section_local_diagnostics(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir()
    write(vault / "raw" / "idea.md", "---\ntype: raw\ntitle: Idea\nstatus: inbox\n---\n")
    snapshot = build_review_snapshot(vault_root=vault, runtime_dir=tmp_path / "runtime", kind="daily", day=date(2026, 7, 16), generated_at=NOW)
    inbox = next(section for section in snapshot.sections if section.section_id == "inbox")
    item = inbox.items[0]
    assert item.sources[0].path == "raw/idea.md"
    assert item.sources[0].content_hash and item.sources[0].content_hash.startswith("sha256:")
    assert item.evidence_fingerprint.startswith("sha256:")
    assert snapshot.content_hash.startswith("sha256:")
    assert "lifeos:item" in render_snapshot_items(snapshot)


def test_refresh_updates_only_managed_blocks_and_keeps_bounded_history(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir(); runtime = tmp_path / "runtime"
    service = ReviewArtifactService(vault_root=vault, runtime_dir=runtime)
    artifact = service.open_or_create(kind="daily", day=date(2026, 7, 16), timezone="UTC", now=NOW, idempotency_key="open")
    path = vault / artifact.path
    path.write_text(path.read_text().replace("### Orientation\n", "### Orientation\n\nHuman text.\n"), encoding="utf-8")
    artifact = service.load_id(artifact.metadata.review_id)
    refreshed, snapshot = refresh_review_snapshot(service=service, artifact=artifact, runtime_dir=runtime, generated_at=NOW, idempotency_key="refresh")
    assert "Human text." in refreshed.body
    assert refreshed.metadata.snapshot_id == snapshot.snapshot_id
    assert refreshed.metadata.snapshot_history[-1].content_hash == snapshot.content_hash
    same, _ = refresh_review_snapshot(service=service, artifact=refreshed, runtime_dir=runtime, generated_at=NOW, idempotency_key="refresh-same")
    assert len(same.metadata.snapshot_history) == 1


def test_snapshot_is_deterministic_except_generation_metadata(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir()
    first = build_review_snapshot(vault_root=vault, runtime_dir=tmp_path / "runtime", kind="weekly", day=date(2026, 7, 16), generated_at=NOW)
    second = build_review_snapshot(vault_root=vault, runtime_dir=tmp_path / "runtime", kind="weekly", day=date(2026, 7, 16), generated_at=NOW)
    assert first == second
