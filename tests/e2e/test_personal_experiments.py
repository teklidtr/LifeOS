from __future__ import annotations

import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication, ProtocolError, ReferenceBridgeClient
from lifeos.experiments import ExperimentArtifactService
from lifeos.experiments.reviews import daily_experiment_section, weekly_experiment_section

NOW = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)


def protocol() -> dict[str, object]:
    return {
        "question": "Does a morning walk relate to focus?",
        "hypothesis": "Focus ratings will be higher during the morning-walk phase.",
        "rationale": "A small routine change can be observed without claiming causation.",
        "intervention": "Walk for 20 minutes after breakfast.",
        "constants": ["same study block"],
        "comparison": "Two-day no-walk baseline.",
        "baseline_requirements": "At least two measured focus observations.",
        "outcome_measures": [
            {
                "measure_id": "focus",
                "display_name": "Focus rating",
                "kind": "rating",
                "role": "primary",
                "cadence": "daily",
                "source": "manual",
                "direction": "increase",
                "valid_min": 1,
                "valid_max": 10,
                "missing_behavior": "report",
                "aggregation": "mean",
            },
            {
                "measure_id": "walked",
                "display_name": "Walk completed",
                "kind": "completion",
                "role": "adherence",
                "cadence": "daily",
                "source": "manual",
                "direction": "increase",
                "missing_behavior": "report",
                "aggregation": "rate",
            },
            {
                "measure_id": "context",
                "display_name": "Context note",
                "kind": "qualitative",
                "role": "contextual",
                "cadence": "daily",
                "source": "manual",
                "direction": "neutral",
                "missing_behavior": "report",
                "aggregation": "none",
            },
        ],
        "phases": [
            {
                "phase_id": "base",
                "name": "Baseline",
                "kind": "baseline",
                "start_date": "2026-07-16",
                "end_date": "2026-07-17",
                "intervention": "",
            },
            {
                "phase_id": "walk",
                "name": "Morning walk",
                "kind": "intervention",
                "start_date": "2026-07-18",
                "end_date": "2026-07-21",
                "intervention": "Morning walk",
            },
        ],
        "adherence_expectation": "Record whether the walk occurred.",
        "confounders": ["sleep", "travel"],
        "risks": [],
        "stop_rules": ["Stop for pain or dizziness."],
        "success_criteria": ["Intervention mean is at least one point higher."],
        "failure_criteria": ["Intervention mean is not higher."],
        "inconclusive_criteria": ["Fewer than two measured primary observations per phase."],
        "schedule": {
            "timezone": "Europe/Istanbul",
            "time": "12:00",
            "window_minutes": 60,
            "grace_minutes": 60,
        },
    }


def client(tmp_path: Path) -> tuple[ReferenceBridgeClient, Path, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = vault / ".lifeos"
    return (
        ReferenceBridgeClient(
            BridgeApplication(vault_root=vault, runtime_dir=runtime, actor_id="e2e")
        ),
        vault,
        runtime,
    )


def observe(
    bridge: ReferenceBridgeClient,
    artifact: dict[str, object],
    measure: str,
    phase: str,
    at: str,
    state: str,
    value: object = None,
    *,
    note: str = "",
    context: list[str] | None = None,
) -> dict[str, object]:
    params: dict[str, object] = {
        "path": artifact["path"],
        "measure_id": measure,
        "phase_id": phase,
        "observed_at": at,
        "state": state,
        "expected_hash": artifact["content_hash"],
        "note": note,
        "context": context or [],
        "now": at,
    }
    if state == "measured":
        params["value"] = value
    return bridge.call("experiment.observation.record", **params)


def test_complete_personal_experiment_lifecycle_analysis_reviews_and_proposal(
    tmp_path: Path,
) -> None:
    bridge, vault, runtime = client(tmp_path)
    capabilities = set(bridge.call("system.handshake", protocol="1.2")["capabilities"])
    assert {
        "experiment.create",
        "experiment.analysis.run",
        "experiment.proposal.create",
        "experiment.recovery.audit",
    } <= capabilities

    item = bridge.call(
        "experiment.create",
        title="Morning walk",
        category="focus",
        protocol=protocol(),
        now=NOW.isoformat(),
    )
    item = bridge.call(
        "experiment.transition",
        path=item["path"],
        target="drafting",
        expected_hash=item["content_hash"],
        now=NOW.isoformat(),
    )
    item = bridge.call(
        "experiment.transition",
        path=item["path"],
        target="baseline",
        expected_hash=item["content_hash"],
        now=NOW.isoformat(),
    )
    item = observe(bridge, item, "focus", "base", "2026-07-16T12:00:00+03:00", "measured", 5)
    item = observe(bridge, item, "focus", "base", "2026-07-17T12:00:00+03:00", "measured", 6)
    item = observe(
        bridge, item, "context", "base", "2026-07-17T12:05:00+03:00", "measured", "Normal study day"
    )
    item = observe(bridge, item, "walked", "base", "2026-07-17T12:10:00+03:00", "not-applicable")
    assert item["metadata"]["observations"][-1]["value"] is None

    item = bridge.call(
        "experiment.transition",
        path=item["path"],
        target="active",
        expected_hash=item["content_hash"],
        now="2026-07-18T08:00:00+03:00",
    )
    daily = daily_experiment_section(
        vault_root=vault,
        runtime_dir=runtime,
        day=date(2026, 7, 18),
        generated_at=datetime.fromisoformat("2026-07-18T12:00:00+03:00"),
    )
    assert daily.section_id == "experiments-daily"
    assert daily.items and "observation" in daily.items[0].detail

    item = observe(bridge, item, "focus", "walk", "2026-07-18T12:00:00+03:00", "measured", 7)
    item = observe(bridge, item, "walked", "walk", "2026-07-18T12:02:00+03:00", "measured", True)
    item = bridge.call(
        "experiment.transition",
        path=item["path"],
        target="paused",
        expected_hash=item["content_hash"],
        reason="Travel day",
        now="2026-07-19T08:00:00+03:00",
    )
    assert all(
        window["status"] == "paused"
        for window in bridge.call(
            "experiment.schedule.due", path=item["path"], now="2026-07-19T12:00:00+03:00"
        )
    )
    changed_protocol = protocol()
    changed_protocol["phases"] = [
        *changed_protocol["phases"][:-1],
        {**changed_protocol["phases"][-1], "end_date": "2026-07-22"},
    ]
    item = bridge.call(
        "experiment.amendment.add",
        path=item["path"],
        protocol=changed_protocol,
        reason="Pause shifted the final day",
        changes=["Intervention end moved to 2026-07-22"],
        expected_hash=item["content_hash"],
        now="2026-07-19T12:30:00+03:00",
    )
    item = bridge.call(
        "experiment.transition",
        path=item["path"],
        target="active",
        expected_hash=item["content_hash"],
        reason="Returned from travel",
        now="2026-07-20T08:00:00+03:00",
    )
    item = observe(bridge, item, "focus", "walk", "2026-07-20T12:00:00+03:00", "measured", 8)
    item = observe(bridge, item, "walked", "walk", "2026-07-20T12:02:00+03:00", "measured", True)
    item = observe(
        bridge,
        item,
        "focus",
        "walk",
        "2026-07-21T12:00:00+03:00",
        "skipped",
        note="Unexpected appointment",
    )
    assert item["metadata"]["observations"][-1]["state"] == "skipped"
    assert item["metadata"]["observations"][-1]["value"] is None

    item = bridge.call(
        "experiment.transition",
        path=item["path"],
        target="completed",
        expected_hash=item["content_hash"],
        now="2026-07-22T18:00:00+03:00",
    )
    item = bridge.call(
        "experiment.analysis.run",
        path=item["path"],
        expected_hash=item["content_hash"],
        save=True,
        now="2026-07-22T18:05:00+03:00",
    )
    analysis = item["metadata"]["analyses"][-1]
    assert analysis["status"] == "ready"
    assert analysis["evidence_kind"] == "descriptive"
    assert "does not establish causation" in " ".join(analysis["limitations"])
    assert set(analysis["observation_ids"]) <= {
        obs["observation_id"] for obs in item["metadata"]["observations"]
    }
    item = bridge.call(
        "experiment.transition",
        path=item["path"],
        target="analyzed",
        expected_hash=item["content_hash"],
        now="2026-07-22T18:10:00+03:00",
    )
    item = bridge.call(
        "experiment.conclusion.record",
        path=item["path"],
        conclusion="supports-hypothesis",
        notes="Observed association only; repeat later.",
        follow_up_decisions=["repeat with a longer baseline"],
        expected_hash=item["content_hash"],
        now="2026-07-22T18:15:00+03:00",
    )

    weekly = weekly_experiment_section(
        vault_root=vault,
        runtime_dir=runtime,
        range_start=date(2026, 7, 16),
        range_end=date(2026, 7, 22),
        generated_at=datetime.fromisoformat("2026-07-22T19:00:00+03:00"),
    )
    assert weekly.items and "measured" in weekly.items[0].detail
    preview = bridge.call(
        "experiment.proposal.preview",
        experiment_path=item["path"],
        action="create-knowledge-note",
        target_path="wiki/morning-walk-finding.md",
        content="# Morning walk finding\n\nObserved association, not causal proof.",
        create_target=True,
    )
    assert preview["source_experiment_hash"] == item["content_hash"]
    result = bridge.call(
        "experiment.proposal.create",
        experiment_path=item["path"],
        action="create-knowledge-note",
        target_path="wiki/morning-walk-finding.md",
        content="# Morning walk finding\n\nObserved association, not causal proof.",
        create_target=True,
    )
    assert (vault / result["proposal_path"] / "patches.json").exists()
    assert not (vault / "wiki" / "morning-walk-finding.md").exists()

    history = bridge.call("experiment.history.rebuild")
    assert history["state"] == "ready"
    assert runtime.exists()
    canonical = (vault / item["path"]).read_text()
    shutil.rmtree(runtime)
    loaded = ExperimentArtifactService(vault_root=vault, runtime_dir=runtime).load(item["path"])
    assert loaded.metadata.conclusion == "supports-hypothesis"
    assert (vault / item["path"]).read_text() == canonical
    rebuilt = bridge.call("experiment.recovery.audit", rebuild=True)
    assert rebuilt["index"]["state"] == "ready"


def test_unsafe_no_model_inconclusive_and_stale_behavior_fail_safely(tmp_path: Path) -> None:
    bridge, vault, _ = client(tmp_path)
    unsafe = protocol()
    unsafe["intervention"] = "Stop prescription medication and double the dose"
    item = bridge.call("experiment.create", title="Unsafe", protocol=unsafe, now=NOW.isoformat())
    item = bridge.call(
        "experiment.transition",
        path=item["path"],
        target="drafting",
        expected_hash=item["content_hash"],
        now=NOW.isoformat(),
    )
    with pytest.raises(ProtocolError) as blocked:
        bridge.call(
            "experiment.transition",
            path=item["path"],
            target="baseline",
            expected_hash=item["content_hash"],
            now=NOW.isoformat(),
        )
    assert blocked.value.code == "unsafe_experiment"
    assert item["metadata"]["safety"]["level"] in {"informational-only", "blocked", "emergency"}

    ordinary = bridge.call(
        "experiment.create", title="Sparse", protocol=protocol(), now="2026-07-17T09:00:00+00:00"
    )
    preview = bridge.call(
        "experiment.analysis.run",
        path=ordinary["path"],
        expected_hash=ordinary["content_hash"],
        save=False,
        now=NOW.isoformat(),
    )
    assert preview["status"] == "insufficient-evidence"
    assert preview["observation_ids"] == []
    assert all(
        "claude" not in key.casefold()
        and "openai" not in key.casefold()
        and "anthropic" not in key.casefold()
        for key in ordinary["metadata"]
    )

    path = vault / ordinary["path"]
    path.write_text(path.read_text() + "\nHuman annotation after workspace load.\n")
    with pytest.raises(ProtocolError) as stale:
        bridge.call(
            "experiment.transition",
            path=ordinary["path"],
            target="drafting",
            expected_hash=ordinary["content_hash"],
            now=NOW.isoformat(),
        )
    assert stale.value.code == "stale_artifact"
    assert "Human annotation" in path.read_text()
