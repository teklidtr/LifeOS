---
id: LIFEOS-1617
title: Make the default pytest command collect duplicate test basenames safely
status: backlog
phase: 16
risk: low
---

# Goal

Make `pytest -q` collect the full suite without import-file mismatch errors.

# Scope

- Configure importlib import mode or package test directories explicitly.
- Verify duplicate basenames such as `test_artifact.py`, `test_contracts.py`,
  and `test_proposals.py` remain independently collected.
- Keep test discovery deterministic in local and release validation.
