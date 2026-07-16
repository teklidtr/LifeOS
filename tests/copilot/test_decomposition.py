from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication
from lifeos.copilot import (
    ActionSuggestion,
    DecompositionError,
    Milestone,
    PlanOption,
    decompose_plan_option,
)


def _option(*, confidence: str = "medium", unresolved: tuple[str, ...] = ()) -> PlanOption:
    return PlanOption(
        schema_version=1,
        option_id="option-cell-focused",
        title="Focused cell foundation",
        strategy="Use a bounded foundation phase.",
        desired_outcome="Explain the first six chapters.",
        boundaries=("No complete textbook backlog.",),
        assumptions=(),
        success_evidence=("Six synthesis notes.",),
        risks=("The pace may be dense.",),
        review_date=None,
        milestones=(
            Milestone(
                "milestone-cell-foundation",
                "Build cell foundation",
                "Explain chapters one and two.",
                wave="current",
            ),
            Milestone(
                "milestone-cell-integration",
                "Integrate mechanisms",
                "Connect chapters three through six.",
                wave="later",
            ),
        ),
        tradeoffs=("Narrow scope for faster feedback.",),
        unresolved_questions=unresolved,
        source_refs=("goals/cell.md",),
        confidence_label=confidence,  # type: ignore[arg-type]
    )


class Adapter:
    def __init__(self, suggestions: tuple[ActionSuggestion, ...]) -> None:
        self.suggestions = suggestions

    def decompose(self, **_: object) -> tuple[ActionSuggestion, ...]:
        return self.suggestions


def _suggestion(
    title: str = "Read and annotate chapter one",
    *,
    task_id: str | None = None,
    blocked_by: tuple[str, ...] = (),
    due: date | None = None,
    kind: str = "study-session",
) -> ActionSuggestion:
    return ActionSuggestion(
        title=title,
        task_id=task_id,
        milestone_id="milestone-cell-foundation",
        duration=60,
        energy="medium",
        motivation="medium",
        mode="study",
        blocked_by=blocked_by,
        due=due,
        rationale="This creates source material for a synthesis note.",
        verification="A chapter note with three explained mechanisms.",
        kind=kind,  # type: ignore[arg-type]
        source_refs=("goals/cell.md",),
    )


def test_fallback_decomposes_only_current_wave_and_preserves_later_milestones() -> None:
    result = decompose_plan_option(option=_option(), horizon="year")
    assert len(result.actions) == 1
    assert result.actions[0].action.milestone_id == "milestone-cell-foundation"
    assert result.milestones[1].wave == "later"
    assert result.rolling_wave_depth == 1
    assert result.redecompose_after
    assert result.actions[0].action.due is None


def test_horizon_and_uncertainty_bound_depth() -> None:
    short = decompose_plan_option(option=_option(), horizon="weeks")
    uncertain = decompose_plan_option(
        option=_option(confidence="low", unresolved=("Capacity?", "Prerequisite?")),
        horizon="months",
    )
    assert short.current_window_days == 7
    assert short.rolling_wave_depth == 2
    assert uncertain.rolling_wave_depth == 1


def test_adapter_actions_are_planner_compatible_and_ids_stable() -> None:
    first = decompose_plan_option(
        option=_option(), horizon="months", adapter=Adapter((_suggestion(),))
    )
    second = decompose_plan_option(
        option=_option(), horizon="months", adapter=Adapter((_suggestion(),))
    )
    assert first.to_dict() == second.to_dict()
    action = first.actions[0].action
    assert action.task_id.startswith("task-cell-focused-cell-foundation")
    assert action.duration == 60
    assert action.energy == "medium"
    assert action.mode == "study"


def test_due_dates_require_explicit_support() -> None:
    deadline = date(2026, 8, 1)
    with pytest.raises(DecompositionError, match="not supported"):
        decompose_plan_option(
            option=_option(),
            horizon="months",
            adapter=Adapter((_suggestion(due=deadline),)),
        )
    supported = decompose_plan_option(
        option=_option(),
        horizon="months",
        adapter=Adapter((_suggestion(due=deadline),)),
        explicit_deadlines={"milestone-cell-foundation": deadline},
    )
    assert supported.actions[0].action.due == deadline


def test_vague_oversized_duplicate_blocked_and_circular_actions_are_rejected() -> None:
    with pytest.raises(DecompositionError, match="action-vague"):
        decompose_plan_option(
            option=_option(), horizon="months", adapter=Adapter((_suggestion("Work on it"),))
        )
    oversized = _suggestion()
    oversized = ActionSuggestion(**{**oversized.__dict__, "duration": 240}) if hasattr(oversized, "__dict__") else ActionSuggestion(
        title=oversized.title,
        milestone_id=oversized.milestone_id,
        duration=240,
        energy=oversized.energy,
        motivation=oversized.motivation,
        mode=oversized.mode,
        rationale=oversized.rationale,
        verification=oversized.verification,
        kind=oversized.kind,
        source_refs=oversized.source_refs,
    )
    with pytest.raises(DecompositionError, match="action-oversized"):
        decompose_plan_option(option=_option(), horizon="months", adapter=Adapter((oversized,)))
    with pytest.raises(DecompositionError, match="action-duplicate"):
        decompose_plan_option(
            option=_option(),
            horizon="months",
            adapter=Adapter((_suggestion(), _suggestion())),
        )
    with pytest.raises(DecompositionError, match="blocker-unknown"):
        decompose_plan_option(
            option=_option(),
            horizon="months",
            adapter=Adapter((_suggestion(blocked_by=("task-missing",)),)),
        )
    a = _suggestion(task_id="task-a", blocked_by=("task-b",))
    b = _suggestion(title="Write chapter one synthesis note", task_id="task-b", blocked_by=("task-a",))
    with pytest.raises(DecompositionError, match="blocker-cycle"):
        decompose_plan_option(option=_option(), horizon="months", adapter=Adapter((a, b)))


def test_study_flashcards_are_bounded_sessions_not_one_task_per_card() -> None:
    with pytest.raises(DecompositionError, match="flashcard-task-too-granular"):
        decompose_plan_option(
            option=_option(),
            horizon="months",
            adapter=Adapter((_suggestion("Review flashcard 17"),)),
        )
    result = decompose_plan_option(
        option=_option(),
        horizon="months",
        adapter=Adapter((_suggestion("Review due flashcards in a 30 minute session"),)),
    )
    assert result.actions[0].kind == "study-session"


def test_task_id_collision_is_rejected() -> None:
    result = decompose_plan_option(option=_option(), horizon="year")
    task_id = result.actions[0].action.task_id
    with pytest.raises(DecompositionError, match="collides"):
        decompose_plan_option(
            option=_option(), horizon="year", existing_task_ids=(task_id,)
        )


def test_bridge_decomposes_generated_option(tmp_path: Path) -> None:
    goal = tmp_path / "goals" / "cell.md"
    goal.parent.mkdir(parents=True)
    goal.write_text(
        "---\ncopilot_schema_version: 1\nid: goal-cell\ntype: goal\ntitle: Learn cell biology\n"
        "status: active\nhorizon: year\nwhy: Understand cells.\n"
        "desired_change: Explain six chapters.\nconstraints: [Four hours weekly]\n---\n",
        encoding="utf-8",
    )
    app = BridgeApplication(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="tester")
    app.dispatch("copilot.session.start", {"goal_path": "goals/cell.md", "session_id": "session-cell"})
    options = app.dispatch("copilot.options.generate", {"session_id": "session-cell", "as_of": "2026-07-16"})
    option_id = options["options"][0]["option_id"]
    result = app.dispatch(
        "copilot.option.decompose",
        {"session_id": "session-cell", "option_id": option_id, "as_of": "2026-07-16"},
    )
    assert result["actions"]
    assert result["milestones"][0]["wave"] == "current"
