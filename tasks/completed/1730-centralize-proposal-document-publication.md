---
id: LIFEOS-1730
title: Centralize proposal-document publication with initial feature consumers
status: completed
phase: hardening
depends_on: []
risk: high
---

# Goal

Introduce one narrow proposal-document publisher and replace the publication mechanics in capture, conversation, experiment, and personal-pattern proposals without moving their domain verification into a framework.

# Problem evidence

At planning HEAD `2996540ee16f574503b4226baa417bf55fea380c`, Serena inspection found parallel directory creation, writes of `proposal.md`/`patches.json`/`review.json`, exception handling, and failed-publication cleanup in `CaptureProposalService.publish`, `ConversationProposalService.publish`, `ExperimentProposalService.publish`, and `patterns.proposals._publish_proposal`/`_open_proposals_root`. The implementations differ in error models and verification placement. Revalidate their important facade/CLI/bridge callers before extraction.

# Scope

- Implement one small publisher for the existing three-document proposal layout using the existing secure filesystem primitives. Select its final module location during implementation; do not expand the derived-state publication framework to cover unrelated canonical lifecycle semantics.
- Route `src/lifeos/captures/proposals.py`, `conversations/proposals.py`, `experiments/proposals.py`, and `patterns/proposals.py` through it in the same task.
- Keep request validation, preview construction, source/target revalidation, identity binding, serialization, review-snapshot production, and feature result/error mapping with their current owners.
- Make the boundary explicit about proposal-root preparation, safe proposal IDs, prepublication verification timing, document bytes, duplicate publication, and cleanup ownership. Preserve differing root-creation and error contracts with small adapters where necessary.
- Inspect the remaining producers covered by LIFEOS-1731 before fixing the API so they can adopt it without a plugin system or a growing set of feature flags.

# Out of scope

- Proposal application, review/lifecycle rules, generated ownership policy, registry transactions, or a generic transaction/persistence framework.
- Migration of the other publication families, which belongs to LIFEOS-1731; ingestion composition belongs to LIFEOS-1732.

# Required invariants

- Preserve canonical document bytes, stable IDs, immutable digest-bound review snapshots, deterministic ordering, and draft-only publication. Publishing a draft never authorizes or applies it.
- Preserve feature-specific revalidation immediately before persistence, errors/codes/messages, duplicate semantics, and return shapes.
- Use descriptor-relative, no-follow access and existing secure write primitives. Cleanup must affect only files/directories owned by the failed attempt, never a pre-existing or replaced proposal directory or a symlink target.
- Keep existing failure/durability behavior or stronger behavior required by current repository safety rules; document any observable difference instead of silently changing the contract. Do not claim three-file publication is a new atomic transaction.

# Acceptance criteria

- [x] All four named families use one publisher; their duplicated write/cleanup implementations are removed.
- [x] Domain verification and error translation remain visible at the feature boundary, including required ordering around review-snapshot creation and persistence.
- [x] Tests cover duplicate IDs, unsafe roots/IDs, symlink or directory replacement, partial writes, review-generation failure, and ownership-safe cleanup using the existing regression inventory and targeted missing cases.
- [x] Fault-injection/monkeypatch seams are audited across the repository; migrations preserve equivalent failure coverage and public call/return/error compatibility.
- [x] The shared API is narrow and exercised by real consumers; no callback registry, configurable file format, lifecycle engine, or parallel publisher abstraction is introduced.
- [x] Record net production/symbol deletion across these consumers and publisher, accounting for adapters. Preserve behavioral/security tests rather than deleting them as duplication.

# Documentation impact

Status: required
- `docs/architecture.md` documents the shared proposal-document publication boundary and the feature-owned verification/review responsibilities.
- The applicable proposal lifecycle, capture, conversation, experiment, and personal-pattern user-manual sections were reviewed. User-visible behavior and lifecycle contracts are unchanged, so no user-manual text change was required.

# Validation

Task-listed validation:

```bash
uv run pytest -q tests/captures tests/conversations tests/experiments tests/patterns tests/proposals
uv run pytest -q tests/facade tests/integration
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
python scripts/validate_tasks.py
```

Execution evidence:

- PR #65 fast-checks on implementation head `d85564e543412471e16f63772cf798bb4f85090c`: GitHub Actions run `34020695813`, success. This includes task workflow validation, documentation impact, manual links, `ruff check .`, `mypy src`, compile, full test collection, and project contract smoke tests.
- PR #65 full-validation on the same implementation head: GitHub Actions run `34020834115`, success. All four full-pytest shards and the aggregate full-test gate passed; the run also passed Ruff, mypy, compile, documentation/manual gates, clean-room MCP setup, home-node service container validation, and ARM64 image build.
- The exact repository-wide `uv run ruff format --check .` command was executed with locked Ruff 0.15.21 in temporary validation PR #66, run `34020536833`. It exposed a pre-existing repository baseline mismatch: 267 files on the `master`-based tree would be reformatted. This is independent of LIFEOS-1730 and is tracked as LIFEOS-1734 rather than expanding this task into repository-wide formatter churn.
- LIFEOS-1730's seven touched Python files were formatted with the same locked Ruff and then checked in isolation. Temporary validation PR #67 run `34020711826` passed `ruff format --check` for all seven touched files. Temporary validation PRs #66 and #67 were closed without merge.
- A local checkout was attempted for direct command execution, but the execution container could not resolve GitHub over the network. Per root `AGENTS.md`, executable CI and isolated validation runs above are the closest practical substitute; the unavailable repo-wide formatter baseline is explicitly recorded rather than reported as passing.

# Review and invariant audit

- Repository-wide caller and monkeypatch/fault-seam searches confirmed capture, conversation, experiment, and personal-pattern public result/error shapes remain feature-owned. Personal-pattern agent assistance keeps its existing `_publish_proposal` adapter seam.
- Remaining LIFEOS-1731 producers were inspected before fixing the shared API. Their differing review/revalidation needs remain outside the publisher, confirming the byte-only publication API does not need callbacks, feature flags, or a plugin registry.
- Normal Codex review found two P2 ownership races. Both were fixed and their threads resolved:
  1. failed cleanup could unlink a concurrently replaced document inside the still-owned directory; file cleanup now proves the installed `(device, inode)` identity before unlinking;
  2. direct creation of the predictable final proposal directory left a race where a replacement directory could be adopted; publication now writes to a private staging directory and publishes the completed directory with an OS-level no-replace rename, so a competing final entry wins without being overwritten or cleaned.
- Security review was skipped by explicit user instruction. No unresolved high-severity or Codex review findings remain.

# Refactor metrics

Compared with starting `master` `6cc3d3978ec862055b6745a5c75949460dcbb358`:

- Production Python change across the shared publisher, secure-write receipt seam, and four migrated consumers: **+468 / -146 lines, net +322**.
- The four migrated feature consumers alone: **+90 / -144 lines, net -54**, despite Ruff-formatting churn in the conversation module.
- `patterns.proposals._open_proposals_root` was deleted. The four feature-local directory/write/cleanup implementations were removed.
- `patterns.proposals._publish_proposal` remains intentionally as a thin compatibility/error-mapping adapter because `patterns.agent_assistance` imports that seam; it no longer owns filesystem publication mechanics.
- Behavioral/security tests were retained and supplemented by `tests/proposals/test_publication.py`; no regression tests were deleted merely as duplication.

# Relevant design decisions

- DD-003, DD-004, DD-031, and DD-034: durable proposals, explicit application, stable layout, and validation.
- DD-065, DD-072, DD-077, and DD-096: feature-specific proposal semantics.
- DD-083 and DD-090: immutable review history and identity/path/version binding.

# Implementation size and sequencing

Medium: one shared primitive plus four consumers. LIFEOS-1731 depends on this task and completes adoption; this task now provides the independently reviewed initial consolidation.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `high`.
- **Reason for the recommendation:** The boundary is narrow, but filesystem ownership, verification timing, and incompatible feature errors need careful design. Sol with high reasoning is sufficient for this bounded security-sensitive extraction without paying for Astra on a largely established mechanism.
