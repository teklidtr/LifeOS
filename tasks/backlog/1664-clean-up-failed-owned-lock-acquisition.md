---
id: LIFEOS-1664
title: Clean up failed owned-lock acquisition
status: backlog
phase: hardening
depends_on:
  - LIFEOS-112.2
risk: high
---

# Goal

Make owned-lock initialization all-or-nothing so a token-write or sync failure does not strand a
lock that blocks future canonical operations, while preserving another owner's replacement lock.

# Problem and current behavior

`OwnedLock.acquire` in `src/lifeos/_owned_lock.py` creates an exclusive lock file, calls `os.write`
and `os.fsync`, and only then records the descriptor in `self.lock_fd`. On an `OSError` during
initialization it closes the descriptor but leaves the newly created pathname behind. Because
`self.lock_fd` remains `None`, a subsequent `release()` cannot remove that failed acquisition.
The next operation encounters the abandoned `O_EXCL` lock and cannot proceed.

The same initialization path ignores the byte count returned by `os.write`. A short write can
make `acquire()` report success with an incomplete token; `release()` then refuses ownership and
leaves the path behind. Fault injection during review reproduced both a failing `fsync` and a
zero-byte write, with the lock still present after release.

This shared helper is used by the proposal transition lock in
`src/lifeos/proposals/lifecycle.py` and both the vault mutation and proposal transition locks in
`src/lifeos/proposals/application.py`. A transient I/O failure can therefore prevent subsequent
proposal lifecycle operations or vault mutations until manual intervention.

# Scope

- Handle complete, partial, zero-progress, and failed token writes deliberately: initialization
  must either persist the full ownership token or fail without claiming an acquired lock.
- Retain sufficient descriptor/identity information during failure cleanup to remove only the
  file created by that acquisition. Check the parent-relative identity before cleanup; do not
  unlink a pathname that has been replaced by a competing owner or a symlink.
- Close descriptors and reset instance acquisition state on every failure path, including a
  failure during cleanup. Preserve the primary failure and make any inability to clean up safe.
- Centralize the fix in `OwnedLock`; audit callers and monkeypatch seams rather than adding
  duplicate cleanup logic to each proposal entry point.

# Out of scope

- Automatically reaping pre-existing locks, PID/age-based unlock policies, or stealing locks.
- Redesigning proposal transactions, recovery records, or cross-device writer coordination.
- Opportunistic changes to the successful release protocol or public exception wording.

# Acceptance criteria

- A token-write or sync error cannot be reported as a successful acquisition. If the just-created
  path is still owned and cleanup is possible, it is removed and a new acquisition can succeed.
- Short writes either complete correctly or take the same safe failure path; no incomplete token
  is accepted as a fully initialized lock.
- Injected removal/replacement of the created path before failure cleanup does not delete the
  replacement entry. Pre-existing locks are never removed by a failed acquisition attempt.
- Descriptors do not leak and `lock_fd`/token state cannot falsely claim ownership after failure.
  Cleanup errors do not silently turn an unsuccessful acquisition into success.
- Existing exclusive-create/no-follow behavior, restrictive mode, random ownership tokens,
  release identity/token checks, context-manager behavior, and canonical mutation serialization
  remain intact.
- Preserve known `LockError`/`OSError` behavior, `LockReleaseResult` fields, and helper call shapes
  unless a required compatibility change is explicitly justified and all callers/tests migrate.

# Regression coverage

- Extend `tests/proposals/test_locking.py` with write failure, sync failure, partial/zero write,
  retry after cleanup, descriptor closure, cleanup failure, and path-replacement fault injection.
- Keep the existing replacement-inode, changed-token, normal release, and context-manager tests.
- Exercise the affected proposal lifecycle/application boundaries to show that failed acquisition
  does not mutate canonical data and that a subsequent permitted attempt can proceed.

# Documentation impact

Status: none
Reason: This restores the existing exclusive owned-lock and failed-operation behavior without
introducing an unlock command, a new recovery policy, or any change to canonical write authority.

# Validation

```bash
rtk .venv/bin/pytest -q tests/proposals/test_locking.py
rtk .venv/bin/pytest -q tests/proposals
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk git diff --check
```

Search every `OwnedLock` consumer and affected exception/monkeypatch seam before broad validation.
Follow `AGENTS.md`'s security-sensitive review requirements before a future merge.

# Relevant decisions

- `AGENTS.md`: canonical mutation, concurrency/data-integrity review, and consolidation safety.
- `docs/architecture.md`: Proposal engine and explicit deterministic application.
- `docs/safety-and-ownership.md`: current-target checks and preservation before canonical writes.
- DD-011, DD-012, and DD-038: read-before-write, deterministic preservation, and stale-write safety.
- Completed LIFEOS-112.2: crash-safe proposal application and ownership-aware lock cleanup.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `high`.
- **Reason for the recommendation:** The diff should be localized, but correct failure cleanup
  requires reasoning about descriptor lifetime, partial I/O, competing path identities, and
  proposal-lock compatibility. Concurrency and data-integrity risk outweigh the small file size.
