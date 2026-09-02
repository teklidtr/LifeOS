from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from lifeos.exports import build_export, export_status
from lifeos.graph import build_graph_view, graph_view_status
from lifeos.publication import (
    PublicationConflictError,
    PublicationError,
    PublicationLock,
    active_generation_path,
    inspect_generation_integrity,
    inspect_publication,
    publish_generation,
    recover_publication,
)


def _write_note(vault: Path, relative: str, body: str) -> None:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _active_file(root: Path, relative: str) -> bytes:
    active = active_generation_path(root)
    assert active is not None
    return (active / relative).read_bytes()



def test_graph_fault_between_payload_and_state_never_becomes_active(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    _write_note(vault, "wiki/note.md", "---\nid: note\n---\nold\n")
    first = build_graph_view(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    assert first.active_generation is not None
    root = runtime / "graphify" / "knowledge"
    prior_graph = _active_file(root, "graph.json")
    prior_state = _active_file(root, "state.json")
    _write_note(vault, "wiki/note.md", "---\nid: note\n---\nnew\n")

    def fault(checkpoint: str) -> None:
        if checkpoint == "after-file:graph.json":
            raise RuntimeError("between graph and state")

    with pytest.raises(RuntimeError, match="between graph and state"):
        build_graph_view(
            vault_root=vault,
            runtime_dir=runtime,
            view_name="knowledge",
            _fault_injector=fault,
        )

    assert _active_file(root, "graph.json") == prior_graph
    assert _active_file(root, "state.json") == prior_state
    assert inspect_publication(root).recovery_state == "none"

def test_graph_fault_after_generation_install_leaves_previous_generation_active(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    _write_note(vault, "wiki/note.md", "---\nid: note\n---\nold\n")
    first = build_graph_view(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    assert first.active_generation is not None
    root = runtime / "graphify" / "knowledge"
    old_graph = _active_file(root, "graph.json")

    _write_note(vault, "wiki/note.md", "---\nid: note\n---\nnew\n")

    def fault(checkpoint: str) -> None:
        if checkpoint == "after-generation-install":
            raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError, match="simulated interruption"):
        build_graph_view(
            vault_root=vault,
            runtime_dir=runtime,
            view_name="knowledge",
            _fault_injector=fault,
        )

    status = graph_view_status(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    assert status.active_generation == first.active_generation
    assert status.recovery_state == "prepared"
    assert status.status == "dirty"
    assert _active_file(root, "graph.json") == old_graph
    active = active_generation_path(root)
    assert active is not None
    assert inspect_generation_integrity(active).state == "valid"

    recovered = build_graph_view(vault_root=vault, runtime_dir=runtime, view_name="knowledge")
    assert recovered.active_generation != first.active_generation
    assert recovered.recovery_state == "none"
    assert not recovered.stale_cleanup


def test_export_fault_after_publication_keeps_new_generation_live(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    _write_note(vault, "study/note.md", "old\n")
    first = build_export(vault_root=vault, runtime_dir=runtime, kind="study-bundle")
    root = runtime / "exports" / "study-bundle"
    old_generation = Path(first.output_dir).name

    _write_note(vault, "study/note.md", "new\n")

    def fault(checkpoint: str) -> None:
        if checkpoint == "after-publication":
            raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError, match="simulated interruption"):
        build_export(
            vault_root=vault,
            runtime_dir=runtime,
            kind="study-bundle",
            _fault_injector=fault,
        )

    status = export_status(vault_root=vault, runtime_dir=runtime, kind="study-bundle")
    assert status.status == "ready"
    assert status.active_generation is not None
    assert status.active_generation != old_generation
    assert status.recovery_state == "published"
    assert _active_file(root, "study/note.md") == b"new\n"

    final = build_export(vault_root=vault, runtime_dir=runtime, kind="study-bundle")
    assert Path(final.output_dir).name == status.active_generation
    assert export_status(vault_root=vault, runtime_dir=runtime, kind="study-bundle").recovery_state == "none"


def test_corrupt_staging_is_rejected_before_publication(tmp_path: Path) -> None:
    root = tmp_path / "publication"

    def corrupt(checkpoint: str) -> None:
        if checkpoint == "after-generation-write":
            staging = next((root / "generations").glob(".staging-*"))
            (staging / "payload.txt").unlink()

    with pytest.raises(PublicationError, match="inventory"):
        publish_generation(
            root=root,
            files={"payload.txt": b"complete"},
            fault_injector=corrupt,
        )

    assert inspect_publication(root).active_generation is None
    assert not (root / "transaction.json").exists()
    assert list((root / "generations").iterdir()) == []


def test_cleanup_failure_after_publication_is_reported_as_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "publication"
    first = publish_generation(root=root, files={"payload.txt": b"old"})
    assert first.active_generation is not None
    original_rmtree = shutil.rmtree

    def fail_old_generation(path: str | Path, *args: object, **kwargs: object) -> None:
        candidate = Path(path)
        if candidate.name == first.active_generation:
            raise PermissionError("cleanup denied")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", fail_old_generation)
    second = publish_generation(root=root, files={"payload.txt": b"new"})

    assert second.active_generation != first.active_generation
    assert second.stale_cleanup
    assert second.recovery_state == "published"
    assert _active_file(root, "payload.txt") == b"new"


def test_recovery_is_idempotent_for_prepared_published_and_complete_phases(
    tmp_path: Path,
) -> None:
    for phase in ("prepared", "published", "complete"):
        root = tmp_path / phase
        generations = root / "generations"
        old = generations / "old"
        new = generations / "new"
        old.mkdir(parents=True)
        new.mkdir()
        (old / "payload").write_text("old", encoding="utf-8")
        (new / "payload").write_text("new", encoding="utf-8")
        (root / "active.json").write_text(
            json.dumps({"schema_version": 1, "generation_id": "new"}),
            encoding="utf-8",
        )
        (root / "transaction.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generation_id": "new",
                    "staging_name": ".staging-new-test",
                    "previous_generation": "old",
                    "phase": phase,
                }
            ),
            encoding="utf-8",
        )

        with PublicationLock(root):
            first = recover_publication(root)
            second = recover_publication(root)

        assert first.active_generation == "new"
        assert second.active_generation == "new"
        assert second.recovery_state == "none"
        assert (new / "payload").read_text(encoding="utf-8") == "new"
        assert not old.exists()


def _write_prepared_journal(
    root: Path,
    *,
    generation_id: object = "new",
    staging_name: object = ".staging-new-test",
    previous_generation: object = "old",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "transaction.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation_id": generation_id,
                "staging_name": staging_name,
                "previous_generation": previous_generation,
                "phase": "prepared",
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("generation_id", ""),
        ("generation_id", "."),
        ("generation_id", ".."),
        ("generation_id", "../victim"),
        ("generation_id", "/absolute"),
        ("generation_id", "nested/name"),
        ("generation_id", "nested\\name"),
        ("generation_id", "nul\x00name"),
        ("generation_id", 7),
        ("staging_name", ""),
        ("staging_name", ".staging-new-"),
        ("staging_name", ".staging-new-."),
        ("staging_name", ".staging-new-.."),
        ("staging_name", ".staging-new-../victim"),
        ("staging_name", ".staging-new-/absolute"),
        ("staging_name", "/.staging-new-test"),
        ("staging_name", ".staging-new-test\\victim"),
        ("staging_name", ".staging-new-test\x00victim"),
        ("staging_name", [".staging-new-test"]),
        ("previous_generation", ""),
        ("previous_generation", "."),
        ("previous_generation", ".."),
        ("previous_generation", "../victim"),
        ("previous_generation", "/absolute"),
        ("previous_generation", "nested/name"),
        ("previous_generation", "nested\\name"),
        ("previous_generation", "nul\x00name"),
        ("previous_generation", {"generation": "old"}),
    ],
)
def test_recovery_rejects_untrusted_journal_path_components_before_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    root = tmp_path / "publication"
    generations = root / "generations"
    (generations / "new").mkdir(parents=True)
    (generations / ".staging-new-test").mkdir()
    outside = tmp_path / "victim"
    outside.write_bytes(b"outside-sentinel")
    journal: dict[str, object] = {
        "generation_id": "new",
        "staging_name": ".staging-new-test",
        "previous_generation": "old",
    }
    journal[field] = value
    _write_prepared_journal(root, **journal)

    cleanup_calls: list[tuple[object, object]] = []

    def intercepted_cleanup(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        cleanup_calls.append((path, kwargs.get("dir_fd")))

    monkeypatch.setattr(shutil, "rmtree", intercepted_cleanup)
    with PublicationLock(root), pytest.raises(PublicationError, match="journal fields"):
        recover_publication(root)

    assert cleanup_calls == []
    assert outside.read_bytes() == b"outside-sentinel"
    assert (root / "transaction.json").exists()


def test_recovery_rejects_journal_candidate_with_unexpected_file_type(
    tmp_path: Path,
) -> None:
    root = tmp_path / "publication"
    generations = root / "generations"
    staging = generations / ".staging-new-test"
    staging.mkdir(parents=True)
    (generations / "new").write_bytes(b"not-a-directory")
    _write_prepared_journal(root)

    with PublicationLock(root), pytest.raises(PublicationError, match="entry is invalid"):
        recover_publication(root)

    assert staging.is_dir()
    assert (generations / "new").read_bytes() == b"not-a-directory"
    assert (root / "transaction.json").exists()


def test_recovery_rejects_symlinked_generations_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "publication"
    outside = tmp_path / "outside-generations"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"outside-sentinel")
    root.mkdir()
    (root / "generations").symlink_to(outside, target_is_directory=True)
    _write_prepared_journal(root)

    with PublicationLock(root), pytest.raises(PublicationError, match="directory is invalid"):
        recover_publication(root)

    assert sentinel.read_bytes() == b"outside-sentinel"
    assert (root / "transaction.json").exists()


def test_recovery_symlink_replacement_cannot_redirect_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "publication"
    generations = root / "generations"
    staging = generations / ".staging-new-test"
    staging.mkdir(parents=True)
    (staging / "payload").write_bytes(b"staged")
    _write_prepared_journal(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"outside-sentinel")
    original_rmtree = shutil.rmtree

    def replace_with_symlink(
        path: str | Path,
        *args: object,
        **kwargs: object,
    ) -> None:
        assert Path(path) == Path(".staging-new-test")
        directory_fd = kwargs.get("dir_fd")
        assert isinstance(directory_fd, int)
        os.rename(
            ".staging-new-test",
            ".staging-new-swapped",
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.symlink(outside, ".staging-new-test", dir_fd=directory_fd)
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", replace_with_symlink)
    with PublicationLock(root), pytest.raises(PublicationError, match="cleanup failed"):
        recover_publication(root)

    assert sentinel.read_bytes() == b"outside-sentinel"
    assert (root / "transaction.json").exists()


def test_identical_builds_use_same_generation_and_bytes(tmp_path: Path) -> None:
    root = tmp_path / "publication"
    files = {"a.txt": b"a", "nested/b.txt": b"b"}

    first = publish_generation(root=root, files=files)
    first_manifest = (root / "active.json").read_bytes()
    second = publish_generation(root=root, files=dict(reversed(tuple(files.items()))))

    assert first.active_generation == second.active_generation
    assert (root / "active.json").read_bytes() == first_manifest
    assert _active_file(root, "nested/b.txt") == b"b"


def test_concurrent_publication_is_rejected_explicitly(tmp_path: Path) -> None:
    root = tmp_path / "publication"

    with PublicationLock(root):
        with pytest.raises(PublicationConflictError, match="already running"):
            publish_generation(root=root, files={"payload": b"data"})
