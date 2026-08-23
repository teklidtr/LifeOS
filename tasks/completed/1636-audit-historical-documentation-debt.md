---
id: LIFEOS-1636
title: Audit historical documentation debt
status: completed
phase: 16
depends_on:
  - LIFEOS-1635
risk: medium
branch: lifeos-1636-documentation-debt-audit
---

# Goal

Bring LifeOS's current documentation back in sync with behavior and contracts already implemented by completed tasks, so future agents and users do not learn an outdated system model.

# Scope

- Review completed tasks and their code changes, prioritizing recent ingestion, Wiki evolution, setup/init, MCP, ownership, registry, proposal, and user-visible workflow work.
- Compare implemented behavior against `docs/user-manual/`, architecture/data-model docs, `docs/design-decisions.md`, setup/operations guidance, and README material.
- Update authoritative current-state docs where behavior exists in code but is missing, stale, or misleading in documentation.
- Prefer user-facing explanations in the user manual and technical contracts in architecture/design docs.
- Record any newly discovered documentation structure problem as a separate backlog task rather than expanding this audit without bound.

# Out of scope

- Changing product behavior merely to match stale documentation.
- Rewriting documentation for style alone when it is already accurate.
- Treating completed task files as a substitute for current-state documentation.

# Acceptance criteria

- A documented audit identifies completed work with missing or stale documentation.
- User-visible implemented behavior is reflected in `docs/user-manual/` where relevant.
- Current architecture/data contracts are reflected in the appropriate technical docs.
- Durable design decisions that are only discoverable from task history are promoted into `docs/design-decisions.md` where appropriate.
- Setup, CLI, MCP, and operational behavior is reflected in setup/operations documentation where relevant.
- Documentation is checked against code/tests rather than inferred from old chat history.
- Manual-link validation and the full repository test suite pass after updates.

# Documentation impact

Status: required

- `docs/user-manual/`: fill user-facing documentation gaps discovered by the audit.
- `docs/architecture.md` and related architecture/data-model docs: reconcile current technical contracts.
- `docs/design-decisions.md`: promote durable decisions that are currently trapped in task history.
- Setup/operations documentation and README: reconcile implemented installation and operational behavior.

# Validation

```bash
uv run python scripts/validate_manual_links.py
uv run ruff check .
uv run mypy src
uv run pytest -q
```

# Completion evidence

The audit used completed tasks as change-history pointers, but code and tests as the source of truth. Evidence checked included `bootstrap.py`, CLI and init integration tests, MCP server/schema tests, registry tools and migrations, ingestion proposal/facade tests, proposal review/application/recovery tests, generated-ownership reconciliation, and cumulative generated-Wiki provenance tests. Recent task history reviewed included LIFEOS-1613, 1624, 1627, 1628, 1629, 1630, 1631, 1632, 1633, 1633A, 1634, and 1635.

## Audit findings and resolutions

| Area | Finding | Resolution |
| --- | --- | --- |
| MCP-only ingestion | Troubleshooting still recommended older single-create, single-update, fixed compound tools and initially suggested `page_kind + slug`. | Updated to the current search/read/context/decide flow with `ingestion_evolve_wiki_proposal`; older routes are documented only as compatibility surfaces. |
| Proposal acceptance | Weekly workflow still described separate Submit, Approve, Apply actions while the desktop flow uses one composite confirmation. | Updated weekly workflow to **Accept changes**, while preserving the internal durable lifecycle explanation. |
| Registry location | `docs/registry.md` named `state.sqlite`, while the shipped default is `<runtime_dir>/registry.db`. | Corrected the documented path to `.lifeos/registry.db` under the default bootstrap. |
| Registry refresh semantics | Docs blurred general registry capabilities with what `lifeos scan` / MCP `registry_refresh` actually refresh. | Clarified that the supported refresh path updates file + proposal indexes; provenance uses the separate `refresh_provenance_index()` path. |
| Registry scope | Architecture implied SQLite stored ownership, task, and graph state. | Narrowed the contract to implemented registry data: file/source facts, generated outputs, proposal indexing, and provenance indexing. |
| Canonical domain inventory | Architecture omitted several implemented canonical areas. | Expanded the inventory and distinguished feature-owned canonical areas from the minimal first-party bootstrap roots. |
| First-party bootstrap | Setup was current, but README still read like an implementation scaffold and the non-destructive bootstrap contract lived mainly in code/task history. | Reframed README around the application-vs-vault model, added the `lifeos init` quick start, documented the architecture boundary, and promoted the contract to DD-088. |

## Verified as already current

No rewrite was made where documentation already matched implementation. This included:

- `docs/user-manual/04-setup-and-installation.md` and the tested `lifeos init` flow;
- generated-ownership restore/release recovery behavior;
- immutable proposal `review.json` history and digest binding;
- cumulative generated-Wiki provenance from LIFEOS-1628;
- MCP local-STDIO runtime policy and `system/instructions.yml` authority;
- the LIFEOS-1635 documentation-impact development gate.

## Durable decision promoted

DD-088 now records the first-party bootstrap contract: LifeOS owns its vault bootstrap; initialization is deterministic and non-destructive; recognized-vault reruns do not rewrite user content; conflicting or partial targets fail closed; and client configuration is not mutated implicitly.

## Follow-up

No additional documentation-structure backlog task was required. Future implementation work is protected by the LIFEOS-1635 documentation-impact gate so new drift should be caught during task completion rather than accumulating into another historical sweep.

## Validation evidence

- PR: #7 (`LIFEOS-1636: Audit historical documentation debt`).
- Documentation-impact gate passed.
- Ruff passed.
- mypy passed over 183 source files.
- Python compilation passed.
- Manual-link validation passed across 15 chapters.
- Full test suite passed: 1523/1523.
- Docker clean-room setup + MCP gate passed.
