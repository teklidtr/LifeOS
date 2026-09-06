---
id: LIFEOS-1729
title: Collapse recovery-readiness runtime patching into static implementation
status: completed
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

- [x] A reviewer can follow `collect_recovery_readiness` to every active implementation using ordinary imports/calls; no runtime rebinding or module-class substitution remains in this subsystem.
- [x] Public compatibility and all existing security/recovery behavior remain covered, including unsupported-platform and injected failure paths.
- [x] Every removed/renamed helper, patch target, return attribute, and changed error string has a repository-wide caller/test audit. Any deliberate private-seam migration is enumerated and preserves equivalent fault coverage.
- [x] The task records removed files/symbols and net production change; obsolete layers disappear instead of becoming new wrappers. No arbitrary LOC target overrides invariants.
- [x] Existing behavioral/security tests remain; only demonstrably obsolete machinery-only assertions may be replaced with equivalent boundary assertions.

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

# Implementation record

- Static ownership is consolidated in `src/lifeos/recovery_readiness.py`; the obsolete
  `_recovery_readiness_base.py` and `_recovery_readiness_impl.py` layers are removed.
- Removed runtime-composition machinery includes `_base_original`, `_impl_original`,
  `_PREVIOUS_BUILD_REPORT`, the `_ORIGINAL_*` saved-dispatch aliases, both
  `_RecoveryModuleProxy` classes, cross-module `setattr` installation, and dynamic export copying.
- Superseded base-only helpers that the runtime patch layer previously deleted at import time are
  removed physically: `_committed_coverage`, `_head_exists`, `_index_flags`,
  `_visible_worktree_paths`, and `_worktree`.
- Review consolidation also removed superseded parallel Git metadata/object-store/query helpers,
  including `_discover_git_directory`, `_copy_regular_metadata`, `_copy_metadata_tree`,
  `_fingerprint_regular_metadata`, `_fingerprint_metadata_tree`, `_reject_split_index`,
  `_pinned_fd_path`, `_open_object_store`, `_validate_object_store`, `_tree_root_oid`,
  `_run_git_presence`, and `_open_object_store_root`. A repo-wide AST/reference sweep found no
  remaining unreferenced top-level private recovery implementation.
- Static composition helpers are named for their narrower role: `_load_scope_filter`,
  `_scan_working_tree_snapshot`, `_classify_worktree_snapshot`, `_assemble_report`, and
  `_latest_visible_commit`. Existing public-module fault injection remains intact. The two tests
  that targeted saved-original machinery now target `_scan_working_tree_snapshot` or assert
  ordinary-module reload behavior while preserving equivalent failure/behavior coverage.
- Final review fixes centralize post-sandbox report finalization through
  `_finalize_sandbox_report`, preserving the pre-consolidation topology/fingerprint revalidation
  for success, no-repository, repository-discovery-error, and generic collection-error paths.
- Production recovery-readiness code changes from 4,398 lines across three modules to 3,345 lines
  in one module after review consolidation, a net reduction of 1,053 production lines.
- `docs/user-manual/04-setup-and-installation.md`,
  `docs/user-manual/07-troubleshooting.md`, and
  `docs/user-manual/17-home-node-runtime-safety.md` were reviewed. No user-visible wording changes
  are required because supported platforms, diagnostic IDs/messages, readiness semantics, and
  recovery guarantees are unchanged.

# Validation record

- Focused recovery/doctor validation after the final review fixes: **107 passed, 43 deselected**.
- Targeted sandbox/error-ordering and repository-discovery compatibility regressions: **3 passed**.
- Locked final-tree validation: `ruff format --check .` passed for 538 files; `ruff check .`
  passed; `mypy src` passed for 235 source files; repo-wide `pytest -q` passed with **2,496 tests**.
- `python scripts/validate_tasks.py` passed and `python scripts/validate_manual_links.py` validated
  all 22 user-manual chapters.
- Repo-wide AST/reference audit passed with no orphan top-level private recovery implementation.
- Clean-head PR `fast-checks` and `obsidian-plugin` checkpoints passed on `ec6df858`.
- Final normal Codex review completed on the clean head with no new review thread and a positive PR
  reaction after all prior P1/P2 findings were resolved. Security review was skipped by explicit
  current-user instruction overriding the repository-default review step.
- Final GitHub `full-validation` run `34051244957` passed on `ec6df858`: all four full pytest
  shards and aggregate `full-test` passed; `docker-setup-e2e` passed clean-room setup/MCP,
  home-node service-container, QEMU/Buildx, and ARM64 home-node image build gates.
- Earlier local full-suite attempts were limited because the provided sandbox lacked the optional
  `mcp` dependency and external DNS; the locked GitHub environment supplied those dependencies
  and completed the required repository-wide and clean-room coverage before task completion.
