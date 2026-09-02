---
id: LIFEOS-1659
title: Restore safe macOS recovery-readiness diagnostics
status: backlog
phase: hardening
depends_on:
  - LIFEOS-1647
risk: high
---

# Goal

Make the documented recovery-readiness diagnostics work on supported macOS and Linux
hosts without weakening the hardened Git/filesystem inspection boundary.

# Problem and evidence

On Darwin, `src/lifeos/_recovery_readiness_impl.py:447` (`_pinned_fd_path`) cannot
expose an opened directory through either `/proc/self/fd/<fd>` or `/dev/fd/<fd>`.
`_discover_pinned_git_directory` in `src/lifeos/recovery_readiness.py` (line 230) requires this before
`_build_sandbox` can inspect Git metadata. `collect_recovery_readiness` consequently
reports unknown Git coverage even for a normal clean, committed repository.

Opening a temporary repository's `.git` directory with `O_RDONLY | O_DIRECTORY`
and calling `_pinned_fd_path(fd, os.fstat(fd))` reproduced
`RecoveryGitError: Platform cannot expose a pinned Git object directory safely`.
The existing clean-committed doctor regression fails because
`last_canonical_commit` is `None`. During LIFEOS-1657 validation, all 54 remaining
full-suite failures were in `tests/cli/test_doctor_recovery*.py` for this reason.

This is a supported-platform correctness gap, not permission to remove macOS
support. The Linux-specific always-on service contract is distinct from the general
CLI: `docs/user-manual/04-setup-and-installation.md` recommends macOS and Linux for
the complete POSIX safety model.

# Scope

- Provide a bounded, portable descriptor-relative metadata snapshot/pinning path.
- Audit directory access together with `_pinned_regular_fd_path` and
  `_snapshot_object_directory`; replacing one failing directory check is not enough
  if the same unsupported mechanism remains in a sibling path.
- Preserve race detection, symlink/hardlink checks, object and descriptor budgets,
  protected/runtime exclusions, and source-scoped Git evidence.
- Add platform-independent fault injection and an actual macOS regression/smoke.

# Out of scope

- Backup providers, synchronization, or a new Git implementation.
- Weakening pinning to unchecked live pathnames.
- Reading canonical note bodies, running hooks/configured commands, network access,
  or modifying canonical/runtime state during diagnostics.
- Changing the Linux-only home-node service contract.

# Acceptance criteria

- Clean, dirty, staged, deleted, untracked, ignored, no-commit, and nested-vault
  repositories yield their documented evidence on both macOS and Linux.
- Genuinely unsupported or unverified states remain explicitly unknown, never
  falsely clean or recoverable.
- Existing adversarial metadata/object replacement, malicious configuration,
  protected-scope, runtime-exclusion, boundedness, and read-only tests remain valid.
- Canonical bytes and mtimes are unchanged by every diagnostic path.
- Required local validation and the security-sensitive review workflow in
  `AGENTS.md` are satisfied without relaxing tests merely to hide platform failures.

# Documentation impact

Status: required

- `docs/architecture.md`: update the Recovery-readiness diagnostics implementation
  boundary and supported platform behavior.
- `docs/user-manual/07-troubleshooting.md`: describe actionable recovery diagnostics
  and any remaining genuine platform limitations.
- Review `docs/user-manual/04-setup-and-installation.md` and
  `docs/user-manual/17-home-node-runtime-safety.md` for consistency; do not conflate
  the general CLI with the Linux-only always-on service.

# Validation

```bash
rtk .venv/bin/pytest -q tests/cli -k doctor_recovery
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk .venv/bin/python scripts/validate_manual_links.py
rtk git diff --check
```

Also run a real macOS doctor smoke and the repository's Linux clean-room/setup
validation. Record unavailable platform checks explicitly.

Test-environment note: the LIFEOS-1657 full run used a disposable test parent under
ignored `.pytest_cache/` and set `GIT_CEILING_DIRECTORIES` to that parent. This avoids
fixtures treating macOS `/private/` temporary paths as protected vault scope or
discovering this checkout's parent Git repository. The 54 recorded failures remained
after that isolation; they are not those fixture-location artifacts. Unix-socket
tests also required execution outside the filesystem sandbox. Preserve the security
tests and request the required execution permission rather than weakening their assertions.

# Relevant decisions

- `AGENTS.md`: filesystem/privacy review boundaries, broad validation, and
  consolidation compatibility requirements.
- DD-001 and DD-002: Markdown authority and deterministic operational evidence.
- DD-033: disposable registry state must not become recovery authority.
- LIFEOS-1647 and the Recovery-readiness diagnostics section of
  `docs/architecture.md` define the existing diagnostic contract.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `xhigh`.
- **Reason for the recommendation:** This is security-sensitive platform work across
  a heavily hardened Git/filesystem boundary. Preserving race resistance, privacy,
  and compatibility requires substantially more reasoning than a path substitution.
