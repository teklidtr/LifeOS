---
id: LIFEOS-1736
title: Add generic reviewed canonical-change facade
status: backlog
phase: hardening
depends_on:
  - LIFEOS-113
  - LIFEOS-1731
  - LIFEOS-1735
risk: high
---

# Goal

Extend the existing typed facade with one generic proposal-producing operation for ordinary
human-owned canonical Markdown changes, so an external agent can compose novel user intents
without requiring a new facade/MCP function for each semantic case.

The agent should be able to say what change it wants and why. LifeOS must continue to own path
validation, target classification, current hashes, ownership, operation selection, provenance,
review snapshots, proposal publication, stale-write protection, and later authorization/application.

# Scope

- Add a typed proposal-producing facade operation in a generic `change.*` namespace, centered on
  `change.propose`.
- Support only a deliberately small initial mutation vocabulary that is broadly composable and can
  be validated safely:
  - create an absent ordinary human-owned Markdown note;
  - update one exact ATX section of an existing ordinary human-owned Markdown note.
- Let the caller provide semantic inputs such as target path, desired title/body or section body,
  rationale, and bounded source/grounding references. Do not require the caller to calculate or
  supply internal ownership hashes, patch hashes, review digests, manifest paths, generator
  bookkeeping, or proposal-document bytes.
- Resolve and verify every referenced imported source from LIFEOS-1735 and every referenced
  canonical Markdown source before proposal publication. Preserve source identity/version and
  provenance in the resulting proposal using existing proposal contracts.
- Reuse the existing proposal engine, human-file patch semantics, shared proposal-document
  publisher, review snapshot binding, stale-target validation, and authorization lifecycle.
- Add one centralized target-eligibility boundary for the generic operation. It must reject targets
  whose semantics are owned by a specialized LifeOS workflow or state machine instead of letting a
  generic tool bypass that domain.
- In particular, the generic operation must not become a back door around existing specialized
  mutation contracts for proposals/system state, captures/attachments, experiments, reviews,
  personal patterns, goal/plan lifecycle, generated ownership, managed blocks, flashcards/study
  schemas, or wiki ingestion where an existing specialized workflow is authoritative.
- Ensure ordinary profile-style notes can be created and section-updated through this path so a
  generic imported personal source can ground durable user context without a `resume_*`,
  `salary_*`, or similar domain API.
- Preserve zero-change as a valid agent outcome. The facade must never manufacture a proposal merely
  because a source was imported or inspected.

# Out of scope

- A universal arbitrary-file write API.
- Whole-file overwrite of existing human-authored Markdown.
- Automatic target-path selection, ontology creation, semantic classification, or document
  summarization inside deterministic LifeOS code.
- Replacing specialized domain proposal builders whose schemas, lifecycles, or invariants carry
  real LifeOS semantics.
- Automatically submitting, approving, or applying the produced draft.
- Direct mutation of canonical Markdown by an agent or adapter.
- Exposing this operation through MCP; that is owned by LIFEOS-1737.

# Required invariants

- New user intent does not imply new deterministic mutation semantics. The generic facade exists to
  compose ordinary Markdown changes; specialized operations remain only where LifeOS must enforce
  genuinely distinct invariants or state transitions.
- Agents provide meaning and desired content; LifeOS derives and enforces hashes, ownership,
  provenance, proposal structure, review binding, stale-write checks, and publication safety.
- Existing specialized workflows cannot be bypassed by choosing `change.propose` instead.
- Human-authored content is never silently rewritten. Existing-note changes are exact-section,
  current-hash-bound proposal operations and stop at draft.
- Imported source references are reverified against canonical capture/attachment identity before
  they can ground a proposal.
- No proposal is created when the requested operation is empty, unsupported, unsafe, stale, or
  targets a domain that requires a specialized workflow.

# Acceptance criteria

- A strict typed `change.propose` facade operation exists and is classified as
  `ToolEffect.PROPOSAL_PRODUCING`.
- The operation can create a reviewable draft for an absent ordinary human-owned note such as
  `profile/career/resume.md`, grounded in an imported source reference, without any résumé-specific
  production code or API.
- The operation can create a current-hash-bound exact-section update proposal for an eligible
  existing ordinary human-owned Markdown note.
- The facade derives current target/source hashes, patch operation type, proposal metadata,
  immutable review snapshot, and publication bytes through existing LifeOS services rather than
  accepting those invariants from the caller.
- Attempts to target specialized/stateful roots or managed/generated content fail with a typed,
  actionable error that directs callers toward the appropriate specialized capability rather than
  silently falling back to generic mutation.
- Missing, changed, stale, unsafe, protected-without-required-intent, or ownership-conflicted
  sources/targets fail closed before draft publication.
- No direct canonical write occurs; successful calls create only draft proposals and retain the
  existing explicit submit/approve/apply lifecycle.
- Regression tests demonstrate that semantically different ordinary intents can use the same
  generic operation while specialized domains remain protected from bypass.
- Focused facade/proposal tests and the broad cross-cutting regression suite pass.

# Documentation impact

Status: required

- `docs/architecture.md`: document the generic ordinary-Markdown proposal boundary and its
  relationship to specialized domain workflows.
- `docs/design-decisions.md`: record the durable rule that user-intent variety is handled by agent
  composition, while new deterministic operations are justified only by distinct LifeOS semantics
  or invariants.

# Validation commands

```bash
uv run pytest -q tests/facade tests/proposals tests/ingestion
uv run pytest -q tests/captures tests/mcp tests/integration
uv run pytest -q
uv run ruff check .
uv run mypy src
python scripts/validate_tasks.py
python scripts/validate_manual_links.py
```

Because this task changes a public proposal-producing facade and canonical mutation trust boundary,
run the broadest practical local pytest suite and perform a repository-wide audit for alternate
proposal/mutation entry points before pushing.

# Relevant design decisions

- DD-001: Markdown remains canonical.
- DD-002: Deterministic facts and semantic interpretation are separate.
- DD-003: Durable proposal mode.
- DD-004: Proposal application is explicit.
- DD-017: Original sources remain immutable.
- DD-036: Python is the sole business-rule engine.
- DD-079: Agent-assisted ingestion is MCP-only and external agents own semantic interpretation.
- LIFEOS-113 / LIFEOS-113.3: external agents provide semantic candidate content while the typed
  facade and LifeOS services own verification, identity, provenance, and draft persistence.
- LIFEOS-1730 and LIFEOS-1731: proposal-document publication is centralized while feature/domain
  owners retain their own semantic and prepublication validation responsibilities.
