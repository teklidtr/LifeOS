import io
import json
from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication, ProtocolError, ReferenceBridgeClient, StdioBridgeServer


def client(tmp_path: Path) -> tuple[BridgeApplication, ReferenceBridgeClient]:
    vault = tmp_path / "vault"; vault.mkdir()
    app = BridgeApplication(vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="oguzhan")
    return app, ReferenceBridgeClient(app)


def test_review_artifact_bridge_open_resume_progress_and_history(tmp_path: Path) -> None:
    app, bridge = client(tmp_path)
    opened = bridge.call(
        "review.artifact.open", kind="daily", day="2026-07-16", timezone="Europe/Istanbul",
        now="2026-07-16T08:00:00+03:00", phase="morning", refresh=True,
        idempotency_key="bridge-review-open",
    )
    artifact = opened["artifact"]
    assert artifact["path"] == "reviews/daily/2026-07-16.md"
    assert opened["active_phase"] == "morning"
    updated = bridge.call(
        "review.artifact.section", review_id=artifact["metadata"]["review_id"], phase_id="morning",
        section_id="attention", action="complete", expected_hash=artifact["content_hash"],
        idempotency_key="bridge-review-section", now="2026-07-16T08:05:00+03:00",
    )
    answered = bridge.call(
        "review.artifact.answer", review_id=artifact["metadata"]["review_id"], prompt_id="morning-intent",
        value="Protect reading time", phase_id="morning", expected_hash=updated["content_hash"],
        idempotency_key="bridge-review-answer", now="2026-07-16T08:06:00+03:00",
    )
    loaded = bridge.call("review.artifact.load", review_id=artifact["metadata"]["review_id"], now="2026-07-16T08:07:00+03:00")
    assert loaded["artifact"]["metadata"]["answers"][0]["value"] == "Protect reading time"
    history = bridge.call("review.artifact.history", kind="daily", limit=10)
    assert history[0]["review_id"] == artifact["metadata"]["review_id"]
    assert (app.daily.vault_root / artifact["path"]).exists()


def test_review_artifact_bridge_stale_write_is_actionable(tmp_path: Path) -> None:
    _, bridge = client(tmp_path)
    opened = bridge.call(
        "review.artifact.open", kind="weekly", day="2026-07-16", timezone="Europe/Istanbul",
        now="2026-07-16T18:00:00+03:00", refresh=True, idempotency_key="weekly-open",
    )
    with pytest.raises(ProtocolError) as caught:
        bridge.call(
            "review.artifact.refresh", review_id=opened["artifact"]["metadata"]["review_id"],
            expected_hash="0" * 64, now="2026-07-16T18:05:00+03:00", idempotency_key="weekly-refresh",
        )
    assert caught.value.code == "stale_write"
    assert caught.value.data and "actual_hash" in caught.value.data


def test_review_artifact_result_is_json_rpc_serializable(tmp_path: Path) -> None:
    app, _ = client(tmp_path)
    request = {
        "jsonrpc": "2.0", "id": "review-1", "method": "review.artifact.open",
        "params": {"kind": "daily", "day": "2026-07-16", "timezone": "Europe/Istanbul", "now": "2026-07-16T08:00:00+03:00", "idempotency_key": "stdio-review"},
    }
    writer = io.StringIO()
    StdioBridgeServer(app, reader=io.StringIO(json.dumps(request) + "\n"), writer=writer).serve()
    response = json.loads(writer.getvalue())
    assert response["result"]["artifact"]["metadata"]["period_start"] == "2026-07-16"
    assert response["result"]["snapshot"]["snapshot_id"].startswith("snapshot:daily:")


def test_review_bridge_rejects_ambiguous_load_and_invalid_kind(tmp_path: Path) -> None:
    _, bridge = client(tmp_path)
    with pytest.raises(ProtocolError) as caught:
        bridge.call("review.artifact.load", review_id="daily-2026-07-16", path="reviews/daily/2026-07-16.md", now="2026-07-16T08:00:00+03:00")
    assert caught.value.code == "invalid_params"
    with pytest.raises(ProtocolError) as caught:
        bridge.call("review.artifact.open", kind="monthly", day="2026-07-16", timezone="UTC", now="2026-07-16T08:00:00+00:00", idempotency_key="bad-kind")
    assert caught.value.code == "invalid_params"


def test_review_migration_and_rebuild_are_explicit_bridge_actions(tmp_path: Path) -> None:
    app, bridge = client(tmp_path)
    reviews = app.daily.vault_root / "reviews"; reviews.mkdir()
    source = reviews / "morning-2026-07-16.md"
    source.write_text(
        "---\ntype: review\nreview_kind: morning\ndate: 2026-07-16\nstatus: active\n---\n\n"
        "# Morning review\n\n<!-- lifeos:managed:start facts -->\nOld facts\n<!-- lifeos:managed:end facts -->\n\n"
        "## Reflection\n\nProtect the morning.\n",
        encoding="utf-8",
    )
    preview = bridge.call("review.artifact.migration.preview")
    assert preview["candidates"][0]["state"] == "ready"
    expected = {item["path"]: item["content_hash"] for item in preview["candidates"][0]["sources"]}
    applied = bridge.call(
        "review.artifact.migration.apply", now="2026-07-16T12:00:00+03:00",
        idempotency_key="bridge-migration", expected_source_hashes=expected,
    )
    assert applied["migrated"] == ["daily-2026-07-16"]
    assert source.exists()
    rebuilt = bridge.call("review.artifact.rebuild")
    assert rebuilt["progress_entries"] == 1
    assert rebuilt["history_entries"] == 1
