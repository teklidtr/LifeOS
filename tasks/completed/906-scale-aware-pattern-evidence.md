---
id: LIFEOS-906
title: Scale-aware personal pattern evidence
status: completed
phase: hardening
depends_on:
  - LIFEOS-901
risk: high
---

# Goal

Strengthen personal-observation findings so effect thresholds, uncertainty, and
data quality are meaningful across different metric scales while preserving
strictly noncausal wording.

# Discovered issue

Current pattern surfacing uses fixed absolute thresholds, including a minimum
correlation magnitude and a fixed activity-day outcome difference. Absolute
activity differences are not comparable across metrics with different units or
ranges. The analysis does not yet expose uncertainty intervals, repeated
measure limitations, freshness, metric-definition compatibility, or enough
variance diagnostics to distinguish weak evidence from stable signal.

# Scope

- Require compatible metric definitions and units before combining values.
- Add minimum variance and usable-range checks.
- Replace raw activity differences with a standardized and raw effect summary.
- Report sample counts, missingness, date range, freshness, and within-person
  repeated-measure limitations.
- Add deterministic uncertainty estimates appropriate to the supported sample
  sizes, with documented fallback when estimation is unreliable.
- Separate evidence strength from effect direction and practical magnitude.
- Keep all findings explicitly labeled as candidate associations, never causes.
- Add wording safeguards for health-adjacent metrics and low-quality evidence.
- Expose reasons why a candidate was withheld.
- Preserve raw source values for audit without exposing them in public exports.

# Out of scope

- Medical diagnosis or treatment recommendations.
- Causal inference from observational journal data.
- Population-level norms or external clinical reference ranges.
- Automated behavior changes based on a surfaced association.
- Combining metrics whose definitions or units are unknown.

# Required tests

- Same raw difference interpreted differently under different metric scales.
- Zero or near-zero variance factor and outcome.
- Sparse activity and control groups.
- Strong-looking effect with wide uncertainty remains low confidence.
- Repeated observations from a small number of days are not treated as
  independent population samples.
- Stale evidence is identified.
- Incompatible units or metric definitions block analysis.
- Missing values and duplicate dates are diagnosed deterministically.
- Every surfaced result includes sample counts, effect representation,
  uncertainty or insufficiency reason, date range, and noncausal caveat.
- Text and JSON outputs use safe, tentative language.

# Acceptance criteria

- Activity comparisons include standardized as well as raw effects.
- Evidence quality accounts for variance, sample size, missingness, freshness,
  and uncertainty.
- No result claims or strongly implies causation.
- Unsupported or incompatible data produces an explicit withheld finding rather
  than a numeric conclusion.
- Output remains deterministic for identical canonical journal data.

# Validation commands

```bash
pytest tests/observation tests/cli/test_observe_cli.py
pytest
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-002: Deterministic facts and semantic interpretation are separate
- DD-005: Status and confidence
- DD-015: Knowledge gaps use evidence signals
- DD-025: Energy and motivation are distinct
- DD-026: Exercise, diet, and hobbies are not merely productivity inputs
- DD-028: Metric definitions act like data types
