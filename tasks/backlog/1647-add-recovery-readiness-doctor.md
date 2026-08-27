---
id: LIFEOS-1647
title: Add recovery-readiness doctor diagnostics for canonical vault data
status: backlog
phase: 16
depends_on: []
risk: medium
---

# Goal

Add a read-only `lifeos doctor` diagnostic surface that answers a practical recovery question:

> If canonical Markdown disappears or this machine fails, what parts of the vault are actually
> recoverable, and what recovery gaps exist right now?

The command must make the LifeOS authority model visible rather than blur it. Canonical Markdown
is durable user state. Disposable `.lifeos/` runtime state is rebuildable and must not be presented
as something whose loss requires restore. Git provides canonical version history, but a local Git
repository alone must never be described as a complete backup because it may disappear with the
same disk and cannot recover new files that were never committed.

The initial doctor should therefore distinguish three concepts explicitly:

1. **Canonical Git coverage**: which canonical paths are represented in committed Git history and
   which current canonical changes are not yet protected by a commit.
2. **External backup/snapshot evidence**: whether LifeOS can deterministically verify protection
   outside the local working copy. Unknown or unverifiable protection must be reported as unknown,
   never silently upgraded to safe.
3. **Disposable runtime**: `.lifeos/` derived/runtime state is not canonical recovery material and
   should be rebuildable from the vault or recreated by the owning subsystem.

The diagnostic is advisory and inspectable. It must not commit, push, restore, rewrite, scan, repair,
or create backups on the user's behalf.

# Scope

- Add `lifeos doctor` to the first-party CLI with human-readable output and a stable `--json` form.
- Load the configured vault through the same configuration boundary used by other first-party CLI
  commands.
- Keep the command read-only with respect to both canonical Markdown and `.lifeos/` runtime state.
- Evaluate recovery readiness from path/Git/filesystem metadata without reading canonical note
  bodies merely to perform diagnostics.
- Scope Git diagnostics to the configured vault and canonical vault paths. A vault nested inside a
  larger repository must not report unrelated repository changes as LifeOS recovery exposure.
- Detect and report at least these Git states:
  - the vault is not covered by a Git repository;
  - the repository exists but has no commit yet;
  - the most recent commit affecting the canonical vault, including its timestamp/age as
    informational evidence;
  - tracked canonical files that are modified, staged, or deleted but not yet committed;
  - untracked canonical Markdown/files that are not represented in committed history;
  - canonical files excluded by Git ignore rules when that exclusion means they are not protected
    by the canonical Git history;
  - a clean canonical working tree where all current canonical files are represented by committed
    history.
- Treat staged-but-uncommitted data as uncommitted for recovery reporting. Staging is not equivalent
  to a durable commit contract.
- Do not use raw age of the last commit as a failure by itself. A vault that has not changed since an
  old commit may still be fully represented in Git. Report commit age, but base actionable Git
  warnings on actual current exposure such as uncommitted/untracked/ignored canonical state.
- Distinguish local version history from independent backup:
  - local Git may prove that committed versions exist locally;
  - a configured remote name or local remote-tracking ref is not sufficient evidence that an
    off-device backup is current;
  - if no supported deterministic backup/snapshot evidence is available, report external backup as
    `unknown`/`not verified` with remediation guidance instead of claiming protection.
- Keep backup detection provider-neutral in the initial implementation. A small internal seam for
  future platform/provider checks is acceptable, but provider-specific Time Machine, ZFS, Btrfs,
  NAS, cloud-sync, or hosting integrations are not required by this task unless an already-existing
  LifeOS contract can verify them deterministically without widening scope.
- Make disposable runtime semantics explicit in the report:
  - `.lifeos/registry.db`, activity logs, indexes, graph/export runtime artifacts, caches, and other
    derived runtime state are not counted as canonical recovery gaps merely because they are absent
    from Git;
  - the doctor must not recommend committing disposable runtime as the fix for a recovery warning.
- Produce stable machine-readable diagnostic identifiers so future UIs/home-node surfaces can reuse
  the same deterministic results without parsing prose. At minimum cover identifiers equivalent to:
  - `recovery.git.repository`
  - `recovery.git.last_canonical_commit`
  - `recovery.git.uncommitted_canonical`
  - `recovery.git.untracked_canonical`
  - `recovery.git.ignored_canonical`
  - `recovery.backup.external`
  - `recovery.runtime.disposable`
- Each diagnostic should have a stable status/severity, concise explanation, and actionable
  remediation where relevant. JSON must preserve the distinction between `pass`, actionable
  warning/failure, informational evidence, and `unknown` rather than flattening all non-pass states.
- Keep output privacy-conscious. Report the minimum path metadata needed to fix a local recovery
  problem and never copy note contents, secrets, bearer tokens, or other canonical body text into
  diagnostics.
- Add regression coverage using temporary Git repositories/vaults rather than depending on the
  developer's real checkout or global Git configuration.

# Out of scope

- Automatically committing, pushing, tagging, or otherwise mutating Git history.
- Building a backup engine, snapshot scheduler, cloud-sync service, or remote repository host.
- Restoring deleted canonical files automatically.
- Treating Git as a substitute for filesystem/NAS/off-device backup.
- Proving that an arbitrary third-party backup contains a complete or restorable copy when LifeOS
  has no deterministic evidence for that claim.
- Provider-specific backup integrations unless they already exist and can be queried through a
  bounded deterministic contract.
- Reworking `lifeos init`, registry refresh, proposal lifecycle, MCP authority, or home-node
  authentication.
- Making disposable `.lifeos/` state canonical or requiring it for vault disaster recovery.
- Reading or semantically interpreting note contents to decide whether a file is important enough
  to back up. Canonical recovery coverage is structural, not an agent judgment.
- Implementing automatic retention policy or deciding how many historical Git commits/snapshots a
  user should keep.

# Acceptance criteria

- [ ] `lifeos doctor` exists, is read-only, and supports deterministic human-readable and `--json`
      output.
- [ ] A vault outside Git is reported as a canonical recovery risk with clear remediation.
- [ ] A newly initialized Git repository with no commit is distinguished from a repository with
      committed canonical history.
- [ ] The doctor reports the latest commit that actually covers/touches the configured canonical
      vault rather than blindly using an unrelated repository-wide commit.
- [ ] Modified, staged, and deleted tracked canonical files are reported as current state not yet
      represented by the latest committed canonical history.
- [ ] Untracked canonical files are reported as recovery exposure; regression coverage proves a new
      never-committed canonical file is not falsely described as recoverable from Git.
- [ ] Canonical files hidden by Git ignore rules are detected/reported when they are outside
      committed canonical history.
- [ ] Disposable `.lifeos/` files are excluded from canonical Git-gap warnings and the output does
      not recommend committing runtime state.
- [ ] An old last-commit timestamp alone does not produce a recovery failure when the canonical
      working tree has not changed; the age remains visible as informational evidence.
- [ ] Local Git history is never labeled as verified off-device backup. When external backup or
      snapshot protection cannot be deterministically verified, the result is explicitly
      `unknown`/`not verified` rather than `pass`.
- [ ] Stable JSON diagnostics include machine-readable IDs, statuses/severities, summaries, and
      remediation fields suitable for later desktop/home-node presentation without parsing text.
- [ ] Diagnostics do not read or emit canonical note bodies and do not expose secrets.
- [ ] Running the doctor leaves canonical files, Git index/history, and `.lifeos/` runtime bytes
      unchanged.
- [ ] Tests cover clean, dirty, staged, deleted, untracked, ignored, no-repository, and no-commit
      scenarios using isolated temporary repositories.
- [ ] Existing CLI behavior and the full test suite remain compatible.

# Documentation impact

Status: required

- `docs/user-manual/07-troubleshooting.md`: document `lifeos doctor`, explain Git coverage versus
  independent backup/snapshot protection, and explain the meaning of `unknown` backup status.
- `docs/user-manual/01-system-architecture.md`: clarify the recovery boundary between canonical
  Markdown and disposable `.lifeos/` runtime state if that distinction is not already explicit
  enough for users.
- `docs/architecture.md`: record the deterministic recovery-diagnostics contract and that local Git
  version history must not be presented as verified independent backup.

If implementation needs a durable new configuration contract for backup providers or recovery
policy, stop and record/update the relevant design decision instead of smuggling that policy into a
CLI implementation detail.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/cli
uv run pytest --import-mode=importlib -q
uv run ruff check src tests
uv run mypy src
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
./scripts/run-setup-integration-docker.sh
```

# Relevant decisions

- DD-001: Markdown remains canonical.
- DD-002: Deterministic facts and semantic interpretation are separate.
- DD-033: SQLite/runtime registry state is disposable and rebuildable rather than canonical
  history.
- DD-038: Canonical writes preserve optimistic concurrency and fail stale mutation rather than
  silently overwriting user state.

# Design notes

The recovery model intentionally has multiple layers rather than one green checkbox:

- **Git history** answers: "Can I recover a previously committed logical version of canonical
  Markdown?"
- **Independent snapshot/backup** answers: "Can I recover current or uncommitted data after local
  filesystem/device loss?"
- **Disposable runtime rebuild** answers: "What can LifeOS recreate without restoring user truth?"

`lifeos doctor` should expose those distinctions. It should not manufacture certainty where the
system has no evidence.