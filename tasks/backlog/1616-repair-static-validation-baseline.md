---
id: LIFEOS-1616
title: Repair the existing Ruff and mypy validation baseline
status: backlog
phase: 16
risk: medium
---

# Goal

Restore clean full-project `ruff check src tests` and `mypy src` validation
without weakening safety-relevant typing.

# Scope

- Resolve the existing E402 findings in `facade/copilot_tools.py`.
- Triage and fix the existing mypy findings across bridge, reviews, feedback,
  daily, copilot, attention, and related modules.
- Preserve behavior with focused tests for every corrected subsystem.

# Out of scope

- Registry refresh wiring.
- Broad formatting or unrelated feature changes.
