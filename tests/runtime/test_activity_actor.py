import json
from pathlib import Path

from lifeos.runtime.activity import (
    ActivityStore,
    push_activity_actor,
    reset_activity_actor,
)


def test_activity_store_persists_request_actor_and_restores_context(tmp_path: Path) -> None:
    store = ActivityStore(tmp_path / ".lifeos")

    token = push_activity_actor("remote-home-node")
    try:
        remote = store.append(tool="vault_list", source_paths=["raw/example.md"])
    finally:
        reset_activity_actor(token)
    local = store.append(tool="vault_list", source_paths=["raw/example.md"])

    assert remote.actor_id == "remote-home-node"
    assert local.actor_id is None
    payloads = [json.loads(line) for line in store.path.read_text(encoding="utf-8").splitlines()]
    assert payloads[0]["actor_id"] == "remote-home-node"
    assert payloads[1]["actor_id"] is None


def test_activity_store_reads_legacy_records_without_actor(tmp_path: Path) -> None:
    store = ActivityStore(tmp_path / ".lifeos")
    store.path.parent.mkdir(parents=True)
    store.path.write_text(
        json.dumps(
            {
                "timestamp": "2026-08-26T00:00:00Z",
                "tool": "vault_search",
                "focus_paths": [],
                "instruction_ids": [],
                "source_paths": [],
                "proposal_id": None,
                "target_paths": [],
                "changed_paths": [],
                "operation_count": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    records = store.read(limit=1)

    assert len(records) == 1
    assert records[0].tool == "vault_search"
    assert records[0].actor_id is None
