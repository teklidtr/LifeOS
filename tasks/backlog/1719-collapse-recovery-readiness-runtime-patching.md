---
id: LIFEOS-1719
title: Collapse recovery-readiness runtime patching into static implementation
status: backlog
phase: hardening
depends_on: []
risk: high
---

# Goal

Make recovery-readiness behavior traceable through ordinary definitions and imports, with one implementation of each operation and unchanged recovery, privacy, security, and public reporting contracts.

# Problem evidence

At planning HEAD `2996540ee16f574503b4226baa417bf55fea380c`, `src/lifeos/recovery_readiness.py`, `src/lifeos/_recovery_readiness_impl.py`, and `src/lifeos/_recovery_readiness_base.py` compose behavior through saved originals, symbol replacement, export loops, and module proxy classes. Serena inspection identified `_impl_original`, `_PREVIOUS_BUILD_REPORT`, `_GitMetadataSandbox`, `collect_recovery_readiness`, and `_RecoveryModuleProxy`. `doctor.collect_doctor` consumes the public collector; recovery tests also exercise private fault-injection seams. Revalidate these locations at implementation HEAD.

# Scope

- Trace the effective collector, report builder, scope filtering, Git metadata sandbox, and filesystem helpers through all three modules before editing.
- Move the effective behavior into statically resolvable functions/classes. Keep a small ordinary public facade or cohesive private modules where useful; one implementation does not require one giant file.
- Remove superseded implementations, runtime assignments into other modules, saved-original dispatch, proxy module classes, and dynamic export copying from this subsystem.
- Preserve public imports, signatures, result types/attributes, report serialization, diagnostic codes/order/messages, and doctor integration. Inventory private monkeypatch targets and migrate any unavoidable injection-seam changes together with all callers and tests.

# Out of scope

- Replacing Git with a library, changing readiness policy, adding backup/restore operations, or modifying unrelated `_recovery_io.py` capture/experiment recovery machinery.
- Status/doctor projection cleanup, retrieval consolidation, or general filesystem/Git framework construction.

# Required invariants

- Collection remains read-only: no canonical edits, commits, pushes, restores, repair, or note-body inspection introduced by the refactor.
- Preserve policy-before-traversal/disclosure, runtime exclusions, protected-scope non-influence, sanitized Git invocation/configuration, literal path handling, and fail-closed unknown results.
- Preserve descriptor pinning, no-follow checks, object-store/metadata bounds, child/root identity checks, topology/fingerprint revalidation, concurrent-change detection, and existing macOS/Linux behavior.
- Backup uncertainty and advisory commit-age information retain their current effect on readiness. Do not weaken tests or return optimistic readiness to accommodate a simpler implementation.

# Acceptance criteria

- [ ] A reviewer can follow `collect_recovery_readiness` to every active implementation using ordinary imports/calls; no runtime rebinding or module-class substitution remains in this subsystem.
- [ ] Public compatibility and all existing security/recovery behavior remain covered, including unsupported-platform and injected failure paths.
- [ ] Every removed/renamed helper, patch target, return attribute, and changed error string has a repository-wide caller/test audit. Any deliberate private-seam migration is enumerated and preserves equivalent fault coverage.
- [ ] The task records removed files/symbols and net production change; obsolete layers disappear instead of becoming new wrappers. No arbitrary LOC target overrides invariants.
- [ ] Existing behavioral/security tests remain; only demonstrably obsolete machinery-only assertions may be replaced with equivalent boundary assertions.

# Documentation impact

Status: required
- `docs/architecture.md`: describe the static recovery-readiness ownership and implementation boundary while retaining the documented platform, privacy, and recovery guarantees.
- Review `docs/user-manual/` for recovery/doctor wording; user-visible semantics are intended to remain unchanged.

# Validation

```bash
uv run pytest -q tests/cli -k 'doctor or recovery'
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
python scripts/validate_tasks.py
```

Exercise the existing macOS/Linux race, Git invocation, metadata/object-store, policy-drift, and failure-injection regressions. Record any platform-only local limitation and use the required CI environment for that coverage. Follow root `AGENTS.md` for the stable normal/security review and final validation checkpoints.

# Relevant design decisions

- DD-001 and DD-002: canonical Markdown and separation of deterministic facts from semantic interpretation.
- DD-033: disposable SQLite state.
- DD-062, DD-089, and DD-090: privacy, one active writer, and separation of identity/path/version.

# Implementation size and sequencing

Large relative to this task set, but confined to one intertwined recovery implementation. Independent of the other refactors; do not split it into independently shipped runtime-patching layers.

# Recommended Model

- **Recommended model/configuration:** `gpt-6-astra`, reasoning effort `high`.
- **Reason for the recommendation:** Resolving the effective implementation across compatibility layers while preserving descriptor races, sanitized Git behavior, and fault-injection compatibility requires substantial semantic reasoning. Astra is justified by recovery/security risk; use Serena symbol/reference navigation to keep the working context focused.
