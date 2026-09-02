from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication, ProtocolError, ReferenceBridgeClient

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc).isoformat()


def client(tmp_path: Path) -> tuple[ReferenceBridgeClient, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    app = BridgeApplication(vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="local")
    return ReferenceBridgeClient(app), vault


@pytest.mark.parametrize(
    "source_entry_point",
    [
        "capture-mutation:merge:key:request:1:1",
        "capture-mutation-source:split:key:request:1:1:cap-result",
    ],
)
def test_capture_create_bridge_rejects_reserved_lineage_before_write(
    tmp_path: Path, source_entry_point: str
) -> None:
    bridge, vault = client(tmp_path)

    with pytest.raises(ProtocolError) as exc:
        bridge.call(
            "capture.create",
            title="Forged lineage",
            capture_type="attachment",
            source_entry_point=source_entry_point,
            now=NOW,
        )

    assert exc.value.code == "reserved_capture_lineage"
    assert exc.value.data == {"field": "source_entry_point"}
    assert not (vault / "captures").exists()


def test_capture_transition_bridge_rejects_reserved_reason_without_write(tmp_path: Path) -> None:
    bridge, vault = client(tmp_path)
    created = bridge.call("capture.create", title="Source", capture_type="attachment", now=NOW)
    path = vault / created["path"]
    before = path.read_bytes()

    with pytest.raises(ProtocolError) as exc:
        bridge.call(
            "capture.transition",
            path=created["path"],
            target="archived",
            expected_hash=created["content_hash"],
            reason="merged into cap-20260902T120000Z-deadbeef",
            now=NOW,
        )

    assert exc.value.code == "reserved_capture_lineage"
    assert exc.value.data == {"field": "reason"}
    assert path.read_bytes() == before


def test_capture_bridge_allows_ordinary_lineage_words(tmp_path: Path) -> None:
    bridge, _ = client(tmp_path)
    created = bridge.call(
        "capture.create",
        title="Ordinary",
        capture_type="attachment",
        source_entry_point="ribbon capture-mutation discussion",
        now=NOW,
    )
    archived = bridge.call(
        "capture.transition",
        path=created["path"],
        target="archived",
        expected_hash=created["content_hash"],
        reason="user merged into notes",
        now=NOW,
    )

    assert archived["metadata"]["lifecycle"][-1]["reason"] == "user merged into notes"
