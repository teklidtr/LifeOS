---
id: LIFEOS-1722
title: Reconcile legacy release validation scripts
status: backlog
phase: hardening
depends_on: []
risk: medium
---

# Goal

Determine whether the repository's older manual release-validation/build script chain still represents the current release contract now that PR/full-validation CI covers a broader system and later feature slices have their own historical validators.

# Scope

- Audit `scripts/validate-release.sh`, `scripts/build-release.sh`, and feature-specific validation scripts against current CI, supported packaging, and release documentation.
- Identify which scripts remain supported entry points versus historical one-off release gates.
- Remove or consolidate redundant scripts only after preserving any guarantees that are not covered elsewhere.
- Ensure any retained release command validates the current product surface rather than stopping at older feature phases.

# Out of scope

- Changing product behavior merely to satisfy an old validation script.
- Weakening current `fast-checks`, `obsidian-plugin`, or `full-validation` guarantees.
- Deleting historical task records.

# Acceptance criteria

- Every retained release/build script has a documented current purpose and caller.
- Historical feature validators with no supported caller are removed or explicitly retained with a non-authoritative purpose.
- The supported release path covers the current package/plugin/runtime contract or delegates to the current authoritative validation path.
- Tests and documentation identify a single understandable release-validation story.

# Documentation impact

Status: required

- Review README/setup/release documentation for any supported manual release entry point.
- Document the retained release-validation path or remove stale references together with retired scripts.

# Validation commands

- `python scripts/validate_tasks.py`
- `pytest -q tests/project`
- run the retained release-validation entry point(s)
- `git diff --check`

# Relevant decisions

- `AGENTS.md`: CI is an independent verification layer; full-validation is the final broad checkpoint.
- Current GitHub workflows: `fast-checks`, `obsidian-plugin`, and labeled `full-validation` are the active PR validation layers.
