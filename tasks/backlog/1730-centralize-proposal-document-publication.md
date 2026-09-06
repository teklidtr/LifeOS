---
id: LIFEOS-1730
title: Centralize proposal-document publication with initial feature consumers
status: backlog
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

- [ ] All four named families use one publisher; their duplicated write/cleanup implementations are removed.
- [ ] Domain verification and error translation remain visible at the feature boundary, including required ordering around review-snapshot creation and persistence.
- [ ] Tests cover duplicate IDs, unsafe roots/IDs, symlink or directory replacement, partial writes, review-generation failure, and ownership-safe cleanup using the existing regression inventory and targeted missing cases.
- [ ] Fault-injection/monkeypatch seams are audited across the repository; migrations preserve equivalent failure coverage and public call/return/error compatibility.
- [ ] The shared API is narrow and exercised by real consumers; no callback registry, configurable file format, lifecycle engine, or parallel publisher abstraction is introduced.
- [ ] Record net production/symbol deletion across these consumers and publisher, accounting for adapters. Preserve behavioral/security tests rather than deleting them as duplication.

# Documentation impact

Status: required
- `docs/architecture.md`: document the shared proposal-document publication boundary and the feature-owned verification/review responsibilities.
- Review applicable capture, conversation, experiment, and personal-pattern manual sections; their user contracts should remain unchanged.

# Validation

```bash
uv run pytest -q tests/captures tests/conversations tests/experiments tests/patterns tests/proposals
uv run pytest -q tests/facade tests/integration
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
python scripts/validate_tasks.py
```

Retain the real feature lifecycle tests as well as publisher failure tests. Follow root `AGENTS.md` for normal/security review and final validation checkpoints.

# Relevant design decisions

- DD-003, DD-004, DD-031, and DD-034: durable proposals, explicit application, stable layout, and validation.
- DD-065, DD-072, DD-077, and DD-096: feature-specific proposal semantics.
- DD-083 and DD-090: immutable review history and identity/path/version binding.

# Implementation size and sequencing

Medium: one shared primitive plus four consumers. LIFEOS-1731 depends on this task and completes adoption; this task must already produce a useful, independently reviewable consolidation.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `high`.
- **Reason for the recommendation:** The boundary is narrow, but filesystem ownership, verification timing, and incompatible feature errors need careful design. Sol with high reasoning is sufficient for this bounded security-sensitive extraction without paying for Astra on a largely established mechanism.
