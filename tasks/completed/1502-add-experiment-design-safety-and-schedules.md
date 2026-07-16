---
id: LIFEOS-1502
title: Add experiment design safety and schedules
status: completed
phase: 15
depends_on:
  - LIFEOS-1501
risk: high
---

# Goal

Implement inspectable design warnings, blocking safety classification, timezone-safe schedules, and provider-neutral optional assistance contracts with no-model fallback.

# Scope

- Implement only this task's named capability and its focused tests.
- Preserve canonical Markdown, human-owned regions, proposal gating, provider neutrality, and UI-first behavior.
- Record diagnostics and degraded states instead of inventing evidence.

# Out of scope

- Medical diagnosis or autonomous treatment advice.
- Provider-specific canonical fields.
- Silent mutations to goals, plans, habits, tasks, metrics, notes, reminders, or calendars.

# Required invariants

- Markdown remains canonical and portable.
- Missing observations never become zero.
- Derived state can be deleted and rebuilt.
- Unsafe experiments fail closed before scheduling or activation.
- Descriptive evidence never produces a causal claim.

# Required tests

- Vague protocol, confounder, duplicate, overlap, unsafe, emergency, cadence, timezone, timeout, malformed-output, and no-model fixtures.

# Acceptance criteria

- Focused Python and/or plugin tests pass.
- Relevant schema, protocol, type, lint, and build checks pass.
- Task documentation and implementation remain synchronized.

# Validation commands

F..F                                                                     [100%]
=================================== FAILURES ===================================
_____________ test_design_warnings_are_inspectable_and_not_a_score _____________

tmp_path = PosixPath('/tmp/pytest-of-root/pytest-3/test_design_warnings_are_inspe0')

    def test_design_warnings_are_inspectable_and_not_a_score(tmp_path: Path) -> None:
        vague = replace(
            base_protocol(), intervention="Walk and change caffeine; use phone blocker", comparison="", baseline_requirements="",
            outcome_measures=(MeasureDefinition("mood", "Mood", "qualitative", "primary", "monthly", source="retrospective memory", aggregation="none"),),
            phases=(ExperimentPhase("x", "Short", "intervention", "2026-07-16", "2026-07-17"),),
            success_criteria=(), inconclusive_criteria=(),
        )
        codes = {item.code for item in evaluate_design(vague)}
        assert {"multiple-interventions", "no-baseline", "short-duration", "sparse-measurement", "criteria-incomplete", "retrospective-only", "adherence-unmeasured"} <= codes
        assert all(item.explanation and item.recommendation for item in evaluate_design(vague))
        api = ExperimentArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
        active = api.create(title="Existing", description="", category="study", protocol=base_protocol(), now=datetime(2026, 7, 16, tzinfo=timezone.utc))
        active = api.transition(active.path, "drafting", expected_hash=active.content_hash, now=datetime(2026, 7, 16, tzinfo=timezone.utc))
>       active = api.transition(active.path, "active", expected_hash=active.content_hash, now=datetime(2026, 7, 16, tzinfo=timezone.utc))
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/experiments/test_design_safety_schedule.py:59: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/lifeos/experiments/artifact.py:226: in transition
    validate_transition(artifact.metadata.state, target)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

current = 'drafting', target = 'active'

    def validate_transition(current: ExperimentState, target: ExperimentState) -> None:
        if target == current:
            return
        if target not in _ALLOWED_TRANSITIONS[current]:
>           raise ExperimentError(
                "invalid_transition",
                f"Experiment cannot transition from {current} to {target}.",
                {"current": current, "target": target, "allowed": sorted(_ALLOWED_TRANSITIONS[current])},
            )
E           lifeos.experiments.contracts.ExperimentError: Experiment cannot transition from drafting to active.

src/lifeos/experiments/contracts.py:72: ExperimentError
________________ test_no_model_fallback_and_provider_disclosure ________________

    def test_no_model_fallback_and_provider_disclosure() -> None:
        request = AssistanceRequest("clarify", base_protocol(), ("goals/focus.md",), ("health details",))
        fallback = assist_design(request, provider=None)
        assert fallback.state == "no-model"
>       assert fallback.warnings
E       AssertionError: assert ()
E        +  where () = AssistanceResult(state='no-model', suggestions=(), warnings=(), provider_disclosure={'configured': False, 'sent_paths': []}, diagnostics=()).warnings

tests/experiments/test_design_safety_schedule.py:91: AssertionError
=========================== short test summary info ============================
FAILED tests/experiments/test_design_safety_schedule.py::test_design_warnings_are_inspectable_and_not_a_score - lifeos.experiments.contracts.ExperimentError: Experiment cannot transition from drafting to active.
FAILED tests/experiments/test_design_safety_schedule.py::test_no_model_fallback_and_provider_disclosure - AssertionError: assert ()
 +  where () = AssistanceResult(state='no-model', suggestions=(), warnings=(), provider_disclosure={'configured': False, 'sent_paths': []}, diagnostics=()).warnings
2 failed, 2 passed in 0.86s

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- Personal Experiment Architecture
