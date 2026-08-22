import io
import json
from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication, ProtocolError, ReferenceBridgeClient, StdioBridgeServer


def app(tmp_path: Path, notifications: list[dict] | None = None) -> BridgeApplication:
    vault = tmp_path / "vault"
    vault.mkdir()
    return BridgeApplication(vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="oguzhan", notify=None if notifications is None else notifications.append)


def test_handshake_and_version_mismatch(tmp_path: Path) -> None:
    client = ReferenceBridgeClient(app(tmp_path))
    result = client.call("system.handshake", protocol="1.2", client_version="0.1")
    assert isinstance(result, dict) and result["actor_id"] == "oguzhan"
    assert result["runtime_schema"] == 1
    assert "feedback.replay" in result["capabilities"]
    assert "feedback.preferences.migrate" in result["capabilities"]
    with pytest.raises(ProtocolError) as caught:
        client.call("system.handshake", protocol="2.0")
    assert caught.value.code == "protocol_mismatch"


def test_unknown_method_and_extra_field_are_rejected(tmp_path: Path) -> None:
    client = ReferenceBridgeClient(app(tmp_path))
    with pytest.raises(ProtocolError) as caught:
        client.call("filesystem.read", path="/etc/passwd")
    assert caught.value.code == "method_not_found"
    with pytest.raises(ProtocolError) as caught:
        client.call("system.health", actor_id="attacker")
    assert caught.value.code == "extra_fields"


def test_duplicate_write_is_idempotent_and_actor_cannot_be_overridden(tmp_path: Path) -> None:
    bridge = app(tmp_path)
    client = ReferenceBridgeClient(bridge)
    params = {"idempotency_key": "capture-1", "kind": "thought", "title": "One", "content": "Body"}
    first = client.call("daily.capture", **params)
    second = client.call("daily.capture", **params)
    assert first == second
    path = bridge.daily.vault_root / first["reference"]["path"]  # type: ignore[index]
    assert path.read_text().count("Body") == 1
    assert "captured_by: oguzhan" in path.read_text()


def test_notifications_are_protocol_frames(tmp_path: Path) -> None:
    notifications: list[dict] = []
    client = ReferenceBridgeClient(app(tmp_path, notifications))
    client.call("daily.capture", idempotency_key="capture-1", kind="thought", title="One")
    assert notifications[0]["method"] == "vault.changed"


def test_stdio_never_mixes_logs_with_frames(tmp_path: Path) -> None:
    request = {"jsonrpc": "2.0", "id": "1", "method": "system.health", "params": {}}
    reader = io.StringIO(json.dumps(request) + "\n")
    writer = io.StringIO()
    assert StdioBridgeServer(app(tmp_path), reader=reader, writer=writer).serve() == 0
    lines = writer.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["result"]["status"] == "healthy"


def test_malformed_json_returns_structured_error(tmp_path: Path) -> None:
    writer = io.StringIO()
    StdioBridgeServer(app(tmp_path), reader=io.StringIO("not-json\n"), writer=writer).serve()
    assert json.loads(writer.getvalue())["error"]["code"] == "parse_error"


def test_proposal_failure_is_typed_and_server_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = app(tmp_path)

    def fail_execute(**_params: object) -> dict[str, object]:
        raise ValueError("Recovery is required before application can continue")

    monkeypatch.setattr(bridge.proposals, "execute", fail_execute)
    requests = (
        {
            "jsonrpc": "2.0",
            "id": "proposal",
            "method": "proposal.execute",
            "params": {
                "proposal_id": "prop-20260714T120000Z-1234abcd",
                "action": "accept",
                "token": "token",
            },
        },
        {"jsonrpc": "2.0", "id": "health", "method": "system.health", "params": {}},
    )
    reader = io.StringIO("".join(json.dumps(request) + "\n" for request in requests))
    writer = io.StringIO()

    assert StdioBridgeServer(bridge, reader=reader, writer=writer).serve() == 0

    frames = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert frames[0]["error"] == {
        "code": "proposal_invalid",
        "message": "Recovery is required before application can continue",
        "data": {},
    }
    assert frames[1]["result"]["status"] == "healthy"


def test_unexpected_dispatch_failure_is_redacted_and_server_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = app(tmp_path)
    original_dispatch = bridge.dispatch
    calls = 0

    def fail_once(method: str, params: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("secret traceback detail /local/path")
        return original_dispatch(method, params)

    monkeypatch.setattr(bridge, "dispatch", fail_once)
    request = {"jsonrpc": "2.0", "method": "system.health", "params": {}}
    reader = io.StringIO(
        json.dumps({**request, "id": "failed"})
        + "\n"
        + json.dumps({**request, "id": "healthy"})
        + "\n"
    )
    writer = io.StringIO()

    assert StdioBridgeServer(bridge, reader=reader, writer=writer).serve() == 0

    frames = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert frames[0]["error"] == {
        "code": "internal_error",
        "message": "The LifeOS bridge could not complete the request.",
        "data": {},
    }
    assert "secret" not in writer.getvalue()
    assert "/local/path" not in writer.getvalue()
    assert frames[1]["result"]["status"] == "healthy"


def test_feedback_release_methods_are_strict_and_read_only(tmp_path: Path) -> None:
    bridge = app(tmp_path)
    client = ReferenceBridgeClient(bridge)
    preferences_path = bridge.daily.vault_root / "system" / "adaptive-planning.yml"
    preferences_path.parent.mkdir(parents=True)
    preferences_path.write_text(
        "enabled: true\ndisabled_signals:\n  - duration\nexcluded_events:\n  - old-1\n",
        encoding="utf-8",
    )

    preview = client.call("feedback.preferences.migrate", dry_run=True)
    assert preview["state"] == "migratable"  # type: ignore[index]
    assert preview["mode"] == "shadow"  # type: ignore[index]
    assert "schema_version" not in preferences_path.read_text(encoding="utf-8")

    migrated = client.call("feedback.preferences.migrate", dry_run=False)
    assert migrated["state"] == "migrated"  # type: ignore[index]
    assert "schema_version: 1" in preferences_path.read_text(encoding="utf-8")

    before = tuple(
        sorted(
            (path.relative_to(bridge.daily.vault_root), path.read_bytes() if path.is_file() else b"")
            for path in bridge.daily.vault_root.rglob("*")
        )
    )
    replay = client.call(
        "feedback.replay",
        contexts=[
            {
                "day": "2026-07-16",
                "available_minutes": 60,
                "energy": "medium",
                "motivation": "medium",
            }
        ],
        mode="shadow",
    )
    after = tuple(
        sorted(
            (path.relative_to(bridge.daily.vault_root), path.read_bytes() if path.is_file() else b"")
            for path in bridge.daily.vault_root.rglob("*")
        )
    )
    assert replay["schema_version"] == 1  # type: ignore[index]
    assert replay["days"][0]["baseline"]["unused_minutes"] == 60  # type: ignore[index]
    assert before == after

    with pytest.raises(ProtocolError) as caught:
        client.call(
            "feedback.replay",
            contexts=[{"day": "2026-07-16", "unknown": True}],
        )
    assert caught.value.code == "extra_fields"
