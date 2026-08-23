---
id: LIFEOS-1636
title: Audit historical documentation debt
status: ready
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
