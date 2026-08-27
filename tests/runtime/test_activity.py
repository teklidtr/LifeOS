import os
from pathlib import Path
from threading import Event, Thread

import pytest

from lifeos.runtime import ActivityStore


def test_activity_store_records_only_routing_metadata(tmp_path: Path) -> None:
    store = ActivityStore(tmp_path / ".lifeos")
    record = store.append(
        tool="vault_context",
        focus_paths=["study/driving-licence/intersections.md"],
        instruction_ids=["driving-exam"],
        source_paths=["goals/pass-driving-licence.md"],
    )

    assert record.tool == "vault_context"
    payload = store.path.read_text(encoding="utf-8")
    assert "driving-exam" in payload
    assert "intersections.md" in payload
    assert "canonical Markdown body" not in payload
    assert store.read(limit=1) == (record,)


def test_activity_store_is_bounded_and_tolerates_missing_state(tmp_path: Path) -> None:
    store = ActivityStore(tmp_path / ".lifeos")
    assert store.read() == ()
    for index in range(3):
        store.append(tool=f"tool-{index}")
    assert [item.tool for item in store.read(limit=2)] == ["tool-1", "tool-2"]


def test_activity_store_write_failure_does_not_break_primary_operation(tmp_path: Path) -> None:
    blocked_runtime = tmp_path / "runtime-file"
    blocked_runtime.write_text("not a directory", encoding="utf-8")
    store = ActivityStore(blocked_runtime)

    record = store.append(tool="vault_read_markdown", source_paths=["wiki/example.md"])

    assert record.tool == "vault_read_markdown"
    assert record.source_paths == ("wiki/example.md",)
    assert not store.path.exists()


@pytest.mark.skipif(not hasattr(os, "link"), reason="hard-link regression requires os.link")
@pytest.mark.parametrize("descriptor_bound", [False, True])
def test_activity_store_rejects_hard_linked_log(
    tmp_path: Path,
    descriptor_bound: bool,
) -> None:
    if descriptor_bound and os.open not in getattr(os, "supports_dir_fd", set()):
        pytest.skip("descriptor-bound regression requires dir_fd support")

    canonical = tmp_path / "human-note.md"
    canonical_body = "# Human-owned note\n\nDo not rewrite me.\n"
    canonical.write_text(canonical_body, encoding="utf-8")

    runtime = tmp_path / ".lifeos"
    activity = runtime / "activity"
    activity.mkdir(parents=True)
    os.link(canonical, activity / "mcp.jsonl")

    runtime_fd: int | None = None
    if descriptor_bound:
        runtime_fd = os.open(
            runtime,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
    store = ActivityStore(runtime, runtime_dir_fd=runtime_fd)
    try:
        record = store.append(tool="vault_context")

        assert record.tool == "vault_context"
        assert canonical.read_text(encoding="utf-8") == canonical_body
        assert store.path.read_text(encoding="utf-8") == canonical_body
        assert store.read() == ()
    finally:
        if runtime_fd is not None:
            os.close(runtime_fd)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO regression requires POSIX mkfifo")
@pytest.mark.parametrize("descriptor_bound", [False, True])
def test_activity_store_does_not_block_on_fifo_log(
    tmp_path: Path,
    descriptor_bound: bool,
) -> None:
    runtime = tmp_path / ".lifeos"
    activity = runtime / "activity"
    activity.mkdir(parents=True)
    os.mkfifo(activity / "mcp.jsonl")

    runtime_fd: int | None = None
    if descriptor_bound:
        runtime_fd = os.open(
            runtime,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
    store = ActivityStore(runtime, runtime_dir_fd=runtime_fd)
    finished = Event()
    outcome: dict[str, object] = {}

    def exercise() -> None:
        outcome["record"] = store.append(tool="vault_context")
        outcome["read"] = store.read()
        finished.set()

    worker = Thread(target=exercise, daemon=True)
    try:
        worker.start()
        assert finished.wait(1.0), "activity FIFO access blocked instead of failing safely"
        worker.join(timeout=0.1)
        assert getattr(outcome["record"], "tool") == "vault_context"
        assert outcome["read"] == ()
    finally:
        if runtime_fd is not None:
            os.close(runtime_fd)
