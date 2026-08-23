from pathlib import Path

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
