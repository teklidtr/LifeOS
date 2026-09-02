---
id: LIFEOS-1658
title: Confine review-item decision markers to structural lines
status: ready
phase: hardening
depends_on:
  - LIFEOS-1302
  - LIFEOS-1657
risk: high
---

# Goal

Prevent marker-looking text in review-item examples or source excerpts from being
treated as visible artifact authorization for a canonical review decision or
proposal reference.

# Problem and current behavior

`artifact_item_fingerprints` in `src/lifeos/reviews/decisions.py` uses the unanchored
`_ITEM_MARKER.finditer` across the entire parsed `items` block. Although LIFEOS-1657
now confines the outer managed block structurally, an inner marker in a fenced
example, quoted source, or inline text still enters the visible-item fingerprint map.
`ReviewDecisionService.decide` uses that map to authorize persisted `item_decisions`
and proposal references. Repeating an ID with the same fingerprint is also accepted;
only duplicates with different fingerprints currently fail.

Reproduce with a valid review artifact whose `items` managed block contains only a
code example of a marker for an otherwise absent item. The current scanner returns
that item as visible; a matching decision request can cross the canonical decision
boundary. Regression tests must demonstrate rejection before the review artifact's
decision/proposal-reference update, not merely that a regular expression stops matching
one string. This includes a rejected `propose_change` decision: the current scanner
does not authorize creation of the separate proposal draft itself.

Compatibility is important: `render_snapshot_items` in `src/lifeos/reviews/snapshot.py`
renders each real marker at the end of an **unindented top-level checkbox-item line**:

```markdown
- [ ] Item title <!-- lifeos:item <item-id> <sha256-fingerprint> -->
```

The marker is not a standalone comment line. Preserve this existing renderer format
and any supported checkbox forms established by current tests/contracts; do not ban
all list markers or require a new artifact layout to fix the authorization defect.

# Scope

- Define a fail-closed structural grammar for `lifeos:item` markers inside the
  parsed `items` managed block.
- Anchor recognition to the existing unindented top-level checkbox-item line with
  one trailing marker, outside valid Markdown fenced code blocks. Reuse LIFEOS-1657's
  shared fence-state grammar rather than adding another inconsistent fence parser.
- Bind each recognized item ID to exactly one fingerprint and reject duplicate,
  conflicting, or otherwise ambiguous marker structure.
- Route review decision authorization through the structural scanner instead of
  unanchored regular-expression matches over arbitrary block text.
- Audit item rendering and fingerprint extraction for compatibility with the
  structural contract.
- Add adversarial regressions for fenced, indented, list-nested, and block-quoted
  marker examples, including proof that a fake marker cannot authorize a
  decision or attach a proposal reference while a normally rendered marker still works.

# Out of scope

- Changing review item IDs, fingerprint algorithms, or canonical artifact
  layout.
- Changing review decision semantics or proposal approval policy.
- Changing draft-creation authorization or adding marker checks to
  `create_review_proposal`, which does not currently use this scanner.
- Implementing a complete CommonMark container parser.
- Refactoring unrelated review rendering or frontmatter parsing.

# Acceptance criteria

- Only one structurally valid, unambiguous `lifeos:item` marker can authorize a
  decision for its exact item ID and fingerprint.
- Marker-looking content inside fenced code, indented code, nested lists, block
  quotes, inline examples, or non-item lines cannot authorize a canonical decision
  or proposal reference. A real top-level checkbox item remains valid.
- Duplicate or conflicting item markers fail closed before canonical state is
  changed.
- Regressions cover both same-ID/same-fingerprint and same-ID/different-fingerprint
  duplicates, false fence closers, longer fences, tabs/indentation, and unchanged
  review-artifact bytes and proposal references after rejected decision requests,
  including `propose_change`.
- Existing valid rendered review artifacts and decision workflows remain
  compatible.
- Focused review tests, Ruff, mypy, and the broadest practical pytest suite pass.

# Documentation impact

Status: none

Reason: this restores the existing contract that visible, structurally rendered
review items authorize decisions; it does not change the artifact format or user
workflow.

# Validation

```bash
rtk .venv/bin/pytest -q tests/reviews
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk git diff --check
```

# Relevant decisions

- `AGENTS.md`: human authority, canonical mutation, and proposal authorization boundaries.
- `docs/review-artifact-architecture.md`: managed item snapshots and evidence-scoped decisions.
- DD-001: canonical Markdown remains authoritative.
- DD-002: deterministic code enforces mutation boundaries.
- DD-009: managed-content authorization is restricted to valid explicit
  structure.
- DD-011 and DD-012: scripted writes read current targets and preserve
  human-owned content.
- DD-038: direct canonical writes retain optimistic concurrency and idempotency
  protections.
- DD-057: review refresh replaces managed snapshots only.
- DD-058: review decisions apply to the exact evidence fingerprint shown in that review.
- DD-059: review follow-up changes remain proposal-gated, not directly applied.
- LIFEOS-1657: managed-block and fence structure is parsed through one shared
  fail-closed boundary.

Extend `tests/reviews/test_decisions.py` and relevant snapshot/artifact tests with
end-to-end authorization rejection and a positive normally rendered-item workflow.
Follow `AGENTS.md`'s security-sensitive review requirements before a future merge.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `high`.
- **Reason for the recommendation:** The parser is an authorization boundary, and a superficially
  stricter grammar can break every valid rendered item. Strong reasoning is needed to distinguish
  structural evidence from examples while preserving existing decision/proposal semantics.
