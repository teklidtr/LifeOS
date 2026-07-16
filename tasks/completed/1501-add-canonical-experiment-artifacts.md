---
id: LIFEOS-1501
title: Add canonical experiment artifacts
status: completed
phase: 15
depends_on:
  - LIFEOS-1500
risk: high
---

# Goal

Implement versioned experiment contracts, validated lifecycle transitions, protocol amendments, canonical Markdown persistence, optimistic writes, and human-owned content preservation.

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

- Creation, lifecycle, amendment, stale-write, duplicate-ID, malformed, and unsupported-schema fixtures.

# Acceptance criteria

- Focused Python and/or plugin tests pass.
- Relevant schema, protocol, type, lint, and build checks pass.
- Task documentation and implementation remain synchronized.

# Validation commands

F.....                                                                   [100%]
=================================== FAILURES ===================================
____________ test_create_round_trip_and_preserve_human_annotations _____________

tmp_path = PosixPath('/tmp/pytest-of-root/pytest-0/test_create_round_trip_and_pre0')

    def test_create_round_trip_and_preserve_human_annotations(tmp_path: Path) -> None:
        api = service(tmp_path)
        created = api.create(title="Morning walk", description="Small focus experiment", category="productivity", protocol=protocol(), now=NOW)
        assert created.metadata.state == "idea"
        assert created.path.startswith("experiments/2026/")
        path = tmp_path / created.path
        path.write_text(path.read_text().replace("## User annotations

", "## User annotations

Keep this sentence.
"))
        loaded = api.load(created.path)
        drafted = api.transition(created.path, "drafting", expected_hash=loaded.content_hash, now=NOW)
>       assert "Keep this sentence." in drafted.human_body
E       AssertionError: assert 'Keep this sentence.' in '## User annotations
'
E        +  where '## User annotations
' = ExperimentArtifact(path='experiments/2026/morning-walk-exp-20260716T090000Z-2bbf4b96.md', content_hash='sha256:ec5544b...(), parent_experiment_id=None, repeated_from_experiment_id=None, schema_version=1), human_body='## User annotations
').human_body

tests/experiments/test_artifact.py:59: AssertionError
=========================== short test summary info ============================
FAILED tests/experiments/test_artifact.py::test_create_round_trip_and_preserve_human_annotations - AssertionError: assert 'Keep this sentence.' in '## User annotations
'
 +  where '## User annotations
' = ExperimentArtifact(path='experiments/2026/morning-walk-exp-20260716T090000Z-2bbf4b96.md', content_hash='sha256:ec5544b...(), parent_experiment_id=None, repeated_from_experiment_id=None, schema_version=1), human_body='## User annotations
').human_body
1 failed, 5 passed in 0.86s

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- Personal Experiment Architecture
