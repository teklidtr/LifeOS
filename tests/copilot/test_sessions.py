from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication, ProtocolError
from lifeos.copilot import (
    PlanningSessionError,
    PlanningSessionService,
    QuestionSuggestion,
    SessionConflictError,
)


def _write_goal(path: Path, *, ready: bool = False, status: str = "active") -> None:
    fields = ""
    if ready:
        fields = (
            "horizon: year\n"
            "why: Build a durable foundation.\n"
            "desired_change: Explain the first six chapters.\n"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "copilot_schema_version: 1\n"
        "id: goal-cell\n"
        "type: goal\n"
        "title: Learn cell biology\n"
        f"status: {status}\n"
        f"{fields}"
        "---\n",
        encoding="utf-8",
    )


class ValidAdapter:
    def suggest_question(self, **_: object) -> QuestionSuggestion:
        return QuestionSuggestion(
            question_id="uncertainty-focus",
            category="uncertainty",
            prompt="Which uncertainty would be cheapest to test before committing to a plan?",
            reason="A reversible test may reduce uncertainty.",
        )


class InvalidAdapter:
    def suggest_question(self, **_: object) -> QuestionSuggestion:
        return QuestionSuggestion(
            question_id="bad-diagnosis",
            category="uncertainty",
            prompt="What is your real subconscious motive and diagnosis?",
            reason="Unsafe speculation.",
        )


def test_deterministic_session_asks_one_focused_question_at_a_time(tmp_path: Path) -> None:
    _write_goal(tmp_path / "goals" / "cell.md")
    service = PlanningSessionService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    first = service.start(goal_path="goals/cell.md", session_id="session-cell")
    assert first.envelope.current_question.question_id == "purpose"
    assert first.envelope.current_question.required is True
    second = service.answer(
        session_id="session-cell",
        question_id="purpose",
        response_kind="answered",
        value="Understand living systems.",
        expected_revision=1,
    )
    assert second.envelope.current_question.question_id == "desired-change"
    assert second.envelope.session.answers[0].value == "Understand living systems."


def test_skip_unknown_not_relevant_and_resume_are_visible(tmp_path: Path) -> None:
    _write_goal(tmp_path / "goals" / "cell.md")
    service = PlanningSessionService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    service.start(goal_path="goals/cell.md", session_id="session-cell")
    service.answer(
        session_id="session-cell",
        question_id="purpose",
        response_kind="unknown",
        expected_revision=1,
    )
    resumed = service.get("session-cell")
    assert resumed.envelope.session.answers[0].response_kind == "unknown"
    assert resumed.envelope.current_question.question_id == "desired-change"
    assert "continue-reflecting" in resumed.recommended_outcomes


def test_ready_goal_needs_no_mandatory_questions(tmp_path: Path) -> None:
    _write_goal(tmp_path / "goals" / "cell.md", ready=True)
    service = PlanningSessionService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    snapshot = service.start(goal_path="goals/cell.md", session_id="session-cell")
    assert snapshot.envelope.session.status == "ready"
    assert snapshot.envelope.current_question.question_id == "constraints"
    assert snapshot.envelope.current_question.required is False


def test_valid_adapter_question_and_invalid_adapter_fallback(tmp_path: Path) -> None:
    _write_goal(tmp_path / "goals" / "cell.md", ready=True)
    valid = PlanningSessionService(
        vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos-valid", adapter=ValidAdapter()
    ).start(goal_path="goals/cell.md", session_id="session-valid")
    assert valid.envelope.current_question.source == "agent-suggestion"

    invalid = PlanningSessionService(
        vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos-invalid", adapter=InvalidAdapter()
    ).start(goal_path="goals/cell.md", session_id="session-invalid")
    assert invalid.envelope.current_question.source == "deterministic"
    assert invalid.envelope.adapter_diagnostics


def test_outcomes_do_not_force_plan_creation(tmp_path: Path) -> None:
    _write_goal(tmp_path / "goals" / "cell.md")
    service = PlanningSessionService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    snapshot = service.start(goal_path="goals/cell.md", session_id="session-cell")
    closed = service.close(
        session_id="session-cell",
        outcome="park",
        label="Park until the autumn",
        expected_revision=snapshot.envelope.session.source_revision,
    )
    assert closed.envelope.session.status == "parked"
    assert closed.envelope.session.decisions[-1].kind == "park"
    with pytest.raises(PlanningSessionError, match="unresolved"):
        service.close(
            session_id="session-cell",
            outcome="ready-to-plan",
            label="Force a plan",
            expected_revision=closed.envelope.session.source_revision,
        )


def test_revision_conflicts_and_goal_edits_are_detected(tmp_path: Path) -> None:
    goal_path = tmp_path / "goals" / "cell.md"
    _write_goal(goal_path)
    service = PlanningSessionService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    service.start(goal_path="goals/cell.md", session_id="session-cell")
    with pytest.raises(SessionConflictError, match="stale"):
        service.answer(
            session_id="session-cell",
            question_id="purpose",
            response_kind="answered",
            value="A reason",
            expected_revision=99,
        )
    goal_path.write_text(goal_path.read_text(encoding="utf-8") + "Changed\n", encoding="utf-8")
    assert service.get("session-cell").source_stale is True


def test_temporary_session_is_recovered_after_interrupted_replace(tmp_path: Path) -> None:
    _write_goal(tmp_path / "goals" / "cell.md")
    runtime = tmp_path / ".lifeos"
    service = PlanningSessionService(vault_root=tmp_path, runtime_dir=runtime)
    snapshot = service.start(goal_path="goals/cell.md", session_id="session-cell")
    target = runtime / "planning-sessions" / "session-cell.json"
    temporary = runtime / "planning-sessions" / ".session-cell.json.tmp"
    temporary.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    target.unlink()
    recovered = service.get("session-cell")
    assert recovered.envelope.session.session_id == snapshot.envelope.session.session_id
    assert target.exists()
    assert not temporary.exists()


def test_unsupported_session_schema_fails_closed(tmp_path: Path) -> None:
    _write_goal(tmp_path / "goals" / "cell.md")
    runtime = tmp_path / ".lifeos"
    service = PlanningSessionService(vault_root=tmp_path, runtime_dir=runtime)
    service.start(goal_path="goals/cell.md", session_id="session-cell")
    path = runtime / "planning-sessions" / "session-cell.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PlanningSessionError, match="unsupported"):
        service.get("session-cell")


def test_bridge_session_flow_and_typed_stale_error(tmp_path: Path) -> None:
    _write_goal(tmp_path / "goals" / "cell.md")
    app = BridgeApplication(
        vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="tester"
    )
    started = app.dispatch(
        "copilot.session.start", {"goal_path": "goals/cell.md", "session_id": "session-cell"}
    )
    assert started["current_question"]["question_id"] == "purpose"
    answered = app.dispatch(
        "copilot.session.answer",
        {
            "session_id": "session-cell",
            "question_id": "purpose",
            "response_kind": "answered",
            "value": "Understand cells.",
            "expected_revision": 1,
        },
    )
    assert answered["session"]["source_revision"] == 2
    with pytest.raises(ProtocolError) as error:
        app.dispatch(
            "copilot.session.answer",
            {
                "session_id": "session-cell",
                "question_id": "desired-change",
                "response_kind": "answered",
                "value": "Explain chapters.",
                "expected_revision": 1,
            },
        )
    assert error.value.code == "copilot_session_stale"
