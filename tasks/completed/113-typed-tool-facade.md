---
id: LIFEOS-113
title: Typed Tool Facade
status: completed
milestone: phase-3-first-ingestion
depends_on: [LIFEOS-106]
---

# Objective
Define a provider-independent typed facade through which AI agents and other adapters may invoke approved LifeOS operations without importing CLI code, SQLite internals, or filesystem implementation details.

# Required design boundary
The facade must wrap existing public LifeOS services. It must not duplicate their business logic.
It should expose only operations genuinely needed by the first agent and ingestion adapter:
- read canonical Markdown source
- query registered source state
- query proposal summaries
- load one proposal
- create a draft proposal through an injected domain service
- request explicit lifecycle operations

# Safety requirements
The facade must distinguish:
- read-only tools
- proposal-producing tools
- consequential lifecycle tools

Consequential operations must retain existing approval and lifecycle requirements.
The tool facade must not:
- auto-approve proposals
- auto-apply proposals
- write final wiki pages directly
- open raw SQLite connections for callers
- allow arbitrary host filesystem paths
- bypass canonical vault-path validation

# Scope control
Because exposing read, write, and lifecycle operations in one unit is too large, this task is an umbrella. It is decomposed into:
- LIFEOS-113.1 Tool request and result models
- LIFEOS-113.2 Read-only LifeOS tools
- LIFEOS-113.3 Proposal-producing tools
- LIFEOS-113.4 Consequential-operation authorization boundary

## Note on Phase 3 Integration
LIFEOS-113.1 and LIFEOS-113.2 form the minimum facade required by the first Pydantic AI ingestion adapter. LIFEOS-113.3 and LIFEOS-113.4 remain optional follow-on facade capabilities and do not block LIFEOS-114 or LIFEOS-203.

# Completion evidence

All four child tasks are complete:
- LIFEOS-113.1 defines immutable provider-independent tool models.
- LIFEOS-113.2 provides vault-bounded read-only Markdown access.
- LIFEOS-113.3 creates reviewable draft wiki proposals without direct final writes.
- LIFEOS-113.4 enforces explicit authorization for submit, approve, and apply.

Final umbrella verification covers the facade model, read-only, proposal-producing,
authorization, consequential-operation, and MCP integration suites. The facade
retains the proposal lifecycle and approval boundaries and does not expose raw
SQLite or arbitrary host filesystem access. MCP input schemas reject unexpected
agent-controlled fields instead of silently discarding them.

Validation evidence:
- facade tests: 108 passed
- MCP server tests: 23 passed
- MCP lifecycle integration tests: 4 passed
- full suite: 844 passed, 1 dependency deprecation warning
- Ruff: passed for `src` and `tests`
- mypy: passed for `src`
- `git diff --check`: passed
