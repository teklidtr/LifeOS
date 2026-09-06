from __future__ import annotations

from pathlib import Path

import pytest

import lifeos.retrieval.service as retrieval_service
from lifeos.coherence import collect_identity_snapshot
from lifeos.entrypoint import main
from lifeos.registry import (
    FileTrackingError,
    Registry,
    list_registered_stable_identities,
    register_scan,
)
from lifeos.retrieval import RetrievalIndex, RetrievalIndexService
from lifeos.retrieval.contracts import RetrievalError
from lifeos.scanner import scan_vault


def _note(stable_id: str, title: str = "Example", body: str = "Body") -> str:
    return f"---\nid: {stable_id}\ntype: concept\ntitle: {title}\n---\n{body}\n"


def _registry(tmp_path: Path) -> Registry:
    registry = Registry(tmp_path / "runtime" / "registry.db")
    registry.initialize()
    return registry


def test_scoped_registry_rejects_symlink_replacement_after_scan(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    note = vault / "wiki" / "public.md"
    note.parent.mkdir(parents=True)
    note.write_text(_note("public-id"), encoding="utf-8")
    entries = scan_vault(vault)
    registry = _registry(tmp_path)

    outside = tmp_path / "outside-secret.md"
    outside.write_text(_note("protected-id", body="secret bytes"), encoding="utf-8")
    note.unlink()
    try:
        note.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable on this platform: {exc}")

    with pytest.raises(FileTrackingError, match="safely hash scoped registry file"):
        register_scan(
            registry,
            vault,
            entries,
            identity_allow_path=lambda path: path == "wiki/public.md",
        )

    with registry.connect_read_only() as connection:
        assert connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0


def test_root_agents_id_is_not_a_canonical_note_identity(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    (vault / "AGENTS.md").write_text(
        _note("shared-id", title="Bootstrap instructions"),
        encoding="utf-8",
    )
    (wiki / "note.md").write_text(_note("shared-id"), encoding="utf-8")
    registry = _registry(tmp_path)

    register_scan(registry, vault, scan_vault(vault))

    identities = list_registered_stable_identities(registry)
    assert [(item.stable_id, item.path) for item in identities] == [("shared-id", "wiki/note.md")]
    with registry.connect_read_only() as connection:
        agents_row = connection.execute(
            "SELECT stable_id, content_hash FROM files WHERE vault_path = 'AGENTS.md'"
        ).fetchone()
    assert agents_row is not None
    assert agents_row["stable_id"] is None
    assert agents_row["content_hash"] is not None

    snapshot = collect_identity_snapshot(vault)
    assert [item.path for item in snapshot.by_stable_id("shared-id")] == ["wiki/note.md"]
    assert snapshot.by_path("AGENTS.md") is None

    runtime = vault / ".lifeos"
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    result = service.rebuild()
    assert result.status == "complete"
    with RetrievalIndex(service.active_path, create=False) as index:
        documents = {item.path: item.document_id for item in index.documents()}
    assert documents["wiki/note.md"] == "id:shared-id"
    assert documents["AGENTS.md"].startswith("path:")


def test_failed_relocation_sync_never_publishes_parked_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    old_path = wiki / "old.md"
    new_path = wiki / "new.md"
    old_path.write_text(
        _note("note-a", body="original relocation marker"),
        encoding="utf-8",
    )
    runtime = vault / ".lifeos"
    service = RetrievalIndexService(vault_root=vault, runtime_dir=runtime)
    service.rebuild()

    old_path.rename(new_path)
    new_path.write_text(
        _note("note-a", body="edited relocation marker"),
        encoding="utf-8",
    )
    real_chunker = retrieval_service.chunk_markdown_file

    def fail_new_path(source, **kwargs):
        if source.relative_path == "wiki/new.md":
            raise RetrievalError("forced_failure", "forced relocation chunk failure")
        return real_chunker(source, **kwargs)

    monkeypatch.setattr(retrieval_service, "chunk_markdown_file", fail_new_path)

    with pytest.raises(RetrievalError, match="forced relocation chunk failure"):
        service.incremental_sync()

    assert service.active_path == runtime / "retrieval" / "index.sqlite3"
    assert not (runtime / "retrieval" / "index.sqlite3.relocation-sync").exists()
    with RetrievalIndex(service.active_path, create=False) as index:
        documents = {item.path: item.document_id for item in index.documents()}
        chunk_paths = {item.path for item in index.chunks()}
    assert documents == {"wiki/old.md": "id:note-a"}
    assert chunk_paths == {"wiki/old.md"}
    assert not any(path.startswith(".lifeos/retrieval-relocations/") for path in documents)
    assert not any(path.startswith(".lifeos/retrieval-relocations/") for path in chunk_paths)


def test_doctor_text_lists_every_required_sync_exclusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "lifeos.yml").write_text(
        "vault_root: .\nruntime_dir: ../node-runtime\n",
        encoding="utf-8",
    )
    real_which = __import__("shutil").which
    monkeypatch.setattr(
        "lifeos.doctor.shutil.which",
        lambda name: None if name == "lifeos-mcp" else real_which(name),
    )

    assert main(["doctor", "--config", str(vault / "lifeos.yml")]) == 0

    output = capsys.readouterr().out
    assert "  required sync exclusions:" in output
    assert "    - .git/" in output
    assert "    - .obsidian/workspace*.json" in output
