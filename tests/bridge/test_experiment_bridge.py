from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication, ProtocolError, ReferenceBridgeClient

NOW = datetime(2026, 7, 16, 9, tzinfo=timezone.utc).isoformat()


def protocol() -> dict[str, object]:
    return {
        "question": "Does walking relate to focus?", "hypothesis": "Focus is higher after walking.",
        "rationale": "Small change", "intervention": "Walk 20 minutes", "constants": ["same study time"],
        "comparison": "No-walk baseline", "baseline_requirements": "Two days",
        "outcome_measures": [{"measure_id": "focus", "display_name": "Focus", "kind": "rating", "role": "primary", "cadence": "daily", "valid_min": 1, "valid_max": 10}],
        "phases": [{"phase_id": "base", "name": "Baseline", "kind": "baseline", "start_date": "2026-07-16", "end_date": "2026-07-17"}, {"phase_id": "walk", "name": "Walk", "kind": "intervention", "start_date": "2026-07-18", "end_date": "2026-07-19"}],
        "adherence_expectation": "Both days", "confounders": ["sleep"], "risks": [], "stop_rules": ["Stop for pain"],
        "success_criteria": ["higher mean"], "failure_criteria": ["not higher"], "inconclusive_criteria": ["missing"],
        "schedule": {"timezone": "UTC", "time": "20:00"},
    }


def client(tmp_path: Path):
    vault = tmp_path / "vault"; vault.mkdir()
    app = BridgeApplication(vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="local")
    return ReferenceBridgeClient(app), vault


def test_experiment_bridge_vertical_slice_and_capabilities(tmp_path: Path) -> None:
    bridge, vault = client(tmp_path)
    handshake = bridge.call("system.handshake", protocol="1.2")
    assert "experiment.analysis.run" in handshake["capabilities"]
    created = bridge.call("experiment.create", title="Walk", category="study", protocol=protocol(), now=NOW)
    assert created["metadata"]["safety"]["level"] in {"ordinary", "caution"}
    warnings = bridge.call("experiment.design.evaluate", protocol=protocol())
    assert isinstance(warnings, list)
    drafted = bridge.call("experiment.transition", path=created["path"], target="drafting", expected_hash=created["content_hash"], now=NOW)
    baseline = bridge.call("experiment.transition", path=drafted["path"], target="baseline", expected_hash=drafted["content_hash"], now=NOW)
    observed = bridge.call("experiment.observation.record", path=baseline["path"], measure_id="focus", phase_id="base", observed_at=NOW, state="measured", value=7, expected_hash=baseline["content_hash"], now=NOW)
    analysis = bridge.call("experiment.analysis.run", path=observed["path"], expected_hash=observed["content_hash"], save=False, now=NOW)
    assert analysis["evidence_kind"] == "descriptive"
    rebuilt = bridge.call("experiment.history.rebuild")
    assert rebuilt["state"] == "ready"
    due = bridge.call("experiment.schedule.due", path=observed["path"], now="2026-07-16T20:00:00+00:00")
    assert isinstance(due, list)
    preview = bridge.call("experiment.proposal.preview", experiment_path=observed["path"], action="create-knowledge-note", target_path="notes/walk.md", content="# Walk finding", create_target=True)
    assert preview["operation"] == "create_file"
    assert not (vault / "notes/walk.md").exists()


def test_bridge_rejects_extra_fields_stale_writes_and_unsafe_activation(tmp_path: Path) -> None:
    bridge, _ = client(tmp_path)
    with pytest.raises(ProtocolError) as extra:
        bridge.call("experiment.create", title="x", protocol=protocol(), surprise=True)
    assert extra.value.code == "extra_fields"
    unsafe = protocol(); unsafe["intervention"] = "Stop prescription medication and change dose"
    created = bridge.call("experiment.create", title="Unsafe", protocol=unsafe, now=NOW)
    drafted = bridge.call("experiment.transition", path=created["path"], target="drafting", expected_hash=created["content_hash"], now=NOW)
    with pytest.raises(ProtocolError) as blocked:
        bridge.call("experiment.transition", path=drafted["path"], target="baseline", expected_hash=drafted["content_hash"], now=NOW)
    assert blocked.value.code == "unsafe_experiment"
    with pytest.raises(ProtocolError) as stale:
        bridge.call("experiment.transition", path=drafted["path"], target="baseline", expected_hash=created["content_hash"], now=NOW)
    assert stale.value.code in {"unsafe_experiment", "stale_artifact"}
