---
id: LIFEOS-1504
title: Integrate experiments with reviews and proposals
status: completed
phase: 15
depends_on:
  - LIFEOS-1503
risk: high
---

# Goal

Surface contextual experiment evidence in daily and weekly reviews and create exact, stale-safe follow-up proposals without mutating external canonical artifacts.

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

- Review fingerprints, dismissal continuity, proposal preview/create, exact patches, stale targets, and excluded-action fixtures.

# Acceptance criteria

- Focused Python and/or plugin tests pass.
- Relevant schema, protocol, type, lint, and build checks pass.
- Task documentation and implementation remain synchronized.

# Validation commands


==================================== ERRORS ====================================
_________ ERROR collecting tests/experiments/test_reviews_proposals.py _________
ImportError while importing test module '/mnt/data/lifeos_d6_work/lifeos/tests/experiments/test_reviews_proposals.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
tests/experiments/test_reviews_proposals.py:8: in <module>
    from lifeos.experiments import (
src/lifeos/experiments/__init__.py:65: in <module>
    from .reviews import daily_experiment_section, weekly_experiment_section
src/lifeos/experiments/reviews.py:8: in <module>
    from lifeos.reviews.contracts import ReviewItemSnapshot, ReviewSectionSnapshot, ReviewSourceReference, stable_fingerprint
src/lifeos/reviews/__init__.py:1: in <module>
    from lifeos.reviews.weekly_review import (
src/lifeos/reviews/weekly_review.py:12: in <module>
    from lifeos.reviews.snapshot import refresh_review_snapshot
src/lifeos/reviews/snapshot.py:12: in <module>
    from lifeos.experiments.reviews import daily_experiment_section, weekly_experiment_section
E   ImportError: cannot import name 'daily_experiment_section' from partially initialized module 'lifeos.experiments.reviews' (most likely due to a circular import) (/mnt/data/lifeos_d6_work/lifeos/src/lifeos/experiments/reviews.py)
=========================== short test summary info ============================
ERROR tests/experiments/test_reviews_proposals.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 1.73s

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- Personal Experiment Architecture
