---
id: LIFEOS-1653
title: Enforce retrieval policy in provider previews
status: completed
phase: hardening
depends_on:
  - LIFEOS-1507
  - LIFEOS-1607
risk: high
---

# Goal

Ensure capture and experiment provider previews use the vault's canonical retrieval policy before
opening or disclosing any canonical payload source.

# Scope

- Centralize the combination of external retrieval policy and explicit protected-scope grants.
- Apply canonical excluded, protected, external-allowlist, and runtime exclusions to capture and
  experiment artifacts and selected notes before content access.
- Apply the same boundary to attachment manifests and to the original path named by the approved
  manifest snapshot before integrity checks or derived-content use.
- Preserve capture-level sensitive-content consent as an additional gate.
- Keep provider payload paths normalized and exact.
- Add regression coverage for both required grants, policy exclusions, manifest indirection,
  pre-read denial, and existing bridge behavior.

# Out of scope

- Changing the retrieval-policy schema or built-in protected-prefix defaults.
- Changing provider execution adapters or adding provider credentials.
- Consolidating the separate goal-planning context policy.
- Changing capture, attachment, or experiment canonical schema versions.

# Acceptance criteria

- A path excluded by `system/retrieval-policy.yml` never enters a provider preview or influences it
  through an unread canonical source.
- A protected path requires both an explicit request grant and a matching
  `external_allowed_prefixes` entry.
- Primary artifacts are denied before load when policy does not authorize them.
- Attachment manifests are policy-checked before parsing, and the manifest-selected original path
  is checked before it is opened or used to select derived content.
- Capture and experiment previews report the normalized path actually read.
- Existing public compatibility seams and ordinary unprotected preview behavior remain intact.
- Focused tests, Ruff, mypy, manual-link validation, and the broad practical pytest suite are run.

# Documentation impact

Status: required

- `docs/user-manual/12-personal-experiments.md`: document canonical policy and dual-grant behavior.
- `docs/user-manual/13-rich-capture.md`: document canonical policy for capture, attachment, and
  neighboring-note previews.

# Validation

```bash
.venv/bin/pytest -q tests/retrieval/test_contracts.py tests/captures/test_privacy_migration_recovery.py tests/captures/test_storage_processing.py tests/experiments/test_migration_privacy_recovery.py tests/bridge/test_capture_bridge.py tests/bridge/test_experiment_bridge.py tests/e2e/test_rich_capture.py
.venv/bin/ruff check src tests
.venv/bin/mypy src/lifeos
.venv/bin/python scripts/validate_manual_links.py
.venv/bin/pytest -q
git diff --check
```

# Validation evidence

- Focused retrieval, capture storage/privacy, experiment privacy, bridge, and rich-capture E2E
  suite: `51 passed`.
- Repository Ruff check: passed.
- Source mypy check: passed with no issues in 212 source files.
- User-manual link validation: passed for all 19 chapters.
- Full local pytest attempt: `1953 passed, 57 failed, 12 skipped`. The 57 failures exactly match
  the established pre-change environment baseline: macOS pinned-Git-directory recovery checks,
  three fixtures that mistake macOS's `/private/...` temporary root for protected vault scope, and
  one sandbox-denied Unix socket bind. The seven new policy regressions account for the increase
  from the prior `1946 passed` baseline.
- `git diff --check`: passed.

# Relevant decisions

- DD-062: protected external disclosure requires policy permission and an explicit request grant.
- DD-071: experiment provider access is bounded, explicitly selected, and default deny.
- DD-076: attachment processing respects protected and excluded scopes before provider use.
- `docs/architecture.md`: provider previews are owned by the experiment and capture services.
