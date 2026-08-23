---
id: LIFEOS-1633
title: Integrate vault runtime policy, context-aware study evolution, and setup validation
status: completed
phase: 16
depends_on:
  - LIFEOS-1632
risk: high
---

# Goal

Make a LifeOS vault self-describing to any MCP-connected agent without requiring the
application repository to be the agent's working directory. Runtime policy belongs to
the MCP server; vault-specific policy belongs to `system/instructions.yml`; relevant
canonical vault content supplies situational context. Study ingestion may use that
context to propose durable wiki evolution plus selective flashcards in one reviewed
atomic draft.

# Design principles

- Application `AGENTS.md` governs development; it is not the runtime agent contract.
- MCP instructions describe universal LifeOS behavior independent of client/project.
- `system/instructions.yml` contains vault-specific/context-specific instructions.
- Folder location provides semantic context, not permission to reason from content.
- Any registered canonical Markdown source may contribute durable wiki knowledge.
- Automatic flashcard proposal generation is study-specific by default; explicit user
  intent may use other supported workflows later.
- Integration tests validate infrastructure deterministically without putting an LLM in
  the pass/fail loop.

# Scope

- Canonicalize `lifeos.yml` in the vault root with `vault_root: .` and `.lifeos` runtime.
- Document/scaffold `system/instructions.yml` and a minimal vault bootstrap `AGENTS.md`.
- Add a bounded `vault_context` runtime surface with explicit focus paths so path/domain
  instructions apply even when lexical retrieval would not surface the focused file.
- Remove `raw/`-only wording from MCP ingestion guidance; registered canonical sources
  such as study, journal, experiments, goals, and raw may ground wiki evolution.
- Add a study-specific bounded proposal contract combining wiki creates/section updates
  with selective generated flashcard creates.
- Permit safe lazy nested parents for reviewed generated flashcards beneath an existing
  canonical `flashcards/` root while retaining all path/symlink/ownership checks.
- Add privacy-bounded MCP activity diagnostics under disposable runtime state and expose
  a read-only activity inspection tool without storing canonical note bodies.
- Fix Setup & Installation documentation, including a concrete Codex `mcp add` command.
- Add clean-environment setup integration tests and a Docker clean-room release smoke.

# Out of scope

- Cookiecutter or `lifeos init` guided bootstrap (LIFEOS-1634).
- LLM-quality evals inside deterministic pytest integration tests.
- Autonomous proposal submit/approve/apply.
- Flashcard generation from non-study sources by default.
- Automatic move/rename/merge of canonical knowledge.

# Acceptance criteria

- A vault-root `lifeos.yml` using `vault_root: .` resolves the vault and `.lifeos`
  runtime correctly from any application working directory.
- Setup documentation creates `system/instructions.yml` and a minimal vault `AGENTS.md`.
- `vault_context(question, focus_paths)` includes valid focused Markdown, lexical
  context, and applicable `system/instructions.yml` rules with inspectable evidence.
- MCP universal instructions clearly distinguish runtime policy from vault-specific
  instructions and do not restrict wiki sources to `raw/` or `study/`.
- Registered sources in `raw/`, `study/`, `journal/`, `experiments/`, and `goals/` can
  ground ordinary wiki evolution.
- The study learning proposal accepts 1..12 distinct combined mutations and supports
  generated wiki creates, wiki exact-section updates, and generated flashcard creates.
- Study flashcards record the study source, optional wiki knowledge refs, learning
  context, and selection rationale; the deterministic layer does not choose what is
  pedagogically important.
- The study-specific proposal tool rejects non-`study/` sources.
- Approved generated flashcard creates may lazily create bounded nested parents only
  beneath an existing `flashcards/` root; missing roots and symlinks fail closed.
- MCP activity inspection reports tool/path/instruction/proposal routing metadata without
  copying canonical Markdown bodies or flashcard answers into runtime logs.
- The documented fresh-vault path is exercised under isolated HOME/XDG directories with
  real CLI subprocesses; MCP handshake/tool calls are tested when MCP dependencies are
  installed.
- A Docker clean-room smoke exists as a secondary CI/release gate and uses the same setup
  contract rather than replacing fast host integration tests.

# Validation

```bash
pytest --import-mode=importlib -q tests/context tests/facade tests/ingestion tests/proposals \
  tests/integration/test_fresh_vault_setup.py tests/integration/test_study_learning_workflow.py
pytest --import-mode=importlib -q
python -m compileall -q src/lifeos
python scripts/validate_manual_links.py
git diff --check
```

Run MCP lifecycle/schema tests and the Docker clean-room smoke when their optional runtime
requirements are available.

# Completion notes

Implemented in `9d3e419` plus the documentation/task completion commit that closes this task.

Validated in this environment:

- 559 tests passed across attention through ingestion domains.
- 733 tests passed across lint/markdown through wiki domains.
- 30 non-MCP integration tests passed, including isolated fresh-vault setup and the
  context-aware study workflow.
- Focused setup/context/proposal/runtime suites passed separately during development.
- `python -m compileall -q src/lifeos tests` passed.
- Manual link validation passed for all 14 chapters.
- First-class review release validation passed (48 tests).
- Semantic retrieval/conversation release validation passed (52 tests).
- `git diff --check` passed.

Environment-limited validation:

- The real MCP SDK tests could not execute in this sandbox because the optional `mcp`
  dependency is not installed and network/package download is unavailable.
- Docker is not installed in this sandbox. The repository therefore includes
  `./scripts/run-setup-integration-docker.sh` as the required local/CI clean-room gate.
  That image installs `dev + mcp`, uses the installed console scripts, and runs MCP server
  schema tests, a real STDIO handshake, and the MCP ingestion lifecycle integration tests.
