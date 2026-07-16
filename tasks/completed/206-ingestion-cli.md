---
id: LIFEOS-206
title: Ingestion CLI command
status: completed
milestone: phase-3-first-ingestion
depends_on: [LIFEOS-202, LIFEOS-203, LIFEOS-204]
risk: low
---

# Objective
Expose proposal-producing ingestion through `lifeos ingest <source-path>`.

# Scope
- Use existing CLI configuration and registry-path conventions.
- Call LIFEOS-202 orchestration service rather than duplicating validation.
- Command must stop after proposal generation and print proposal ID/location.
- Define stable behavior for missing, unregistered, changed, unsupported, or failed sources/proposals.
- Define a backend-construction/dependency-injection seam so tests can run real CLI with fake backend.

# Expected files
- `src/lifeos/cli.py`
- `src/lifeos/ingestion/backend_factory.py`
- `tests/cli/test_ingest_cli.py`

# Non-goals
- Interactive approval or automatic application
- Direct provenance indexing, web UI, bulk ingestion

# Acceptance criteria
- Valid source creates one reviewable proposal; canonical wiki remains untouched.
- Errors use stable exit codes and stderr.
- Command uses configured analysis adapter and can be tested with fake backend.
- No lifecycle transition occurs automatically.

# Focused test plan
- valid source creates one draft proposal
- proposal ID and path printed
- source outside vault rejected
- unregistered source rejected
- changed source rejected
- analysis failure
- proposal-generation failure
- final wiki page untouched
- no submit, approve, or apply transition
- fake backend injection through the public CLI path

Implementation has not begun.

Evidence: Commit a571fcfeb0e5442b65afaaae3bae8ece0b357da3 passed all tests.

*Note: Reclassified as part of the optional embedded-agent branch.*
