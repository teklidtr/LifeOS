---
id: LIFEOS-904
title: Typed instruction routing and token-aware context search
status: completed
phase: hardening
depends_on:
  - LIFEOS-901
risk: medium
---

# Goal

Turn context-pack instruction loading into an explicit typed allowlist and make
lexical routing score meaningful tokens rather than arbitrary substrings.

# Discovered issue

The current instruction loader exposes stripped YAML text lines without a typed
schema that proves instruction authority, scope, or applicability. This falls
short of the explicit instruction allowlist boundary. Lexical search also uses
substring counting, so short terms can match unrelated words, for example
`art` matching `heart`, and scoring evidence is not sufficiently inspectable.

# Scope

- Define a versioned typed instruction model with stable ID, scope, applicable
  paths or domains, priority, authority class, and instruction text.
- Load only explicitly allowed instruction sources.
- Validate instruction metadata and report malformed or unauthorized entries.
- Resolve applicability against the query and candidate source path.
- Keep system, repository, scope, and note-local instructions distinguishable.
- Tokenize query and source fields deterministically with Unicode-aware word
  boundaries.
- Score title, description, path, and body matches with documented weights.
- Prevent substring-only false positives unless an explicit fuzzy mode is
  selected.
- Include per-term and per-field score evidence in inspectable context packs.
- Preserve deterministic tie-breaking and output limits.

# Out of scope

- Embedding or vector retrieval.
- Allowing arbitrary notes to become trusted instructions.
- LLM-based reranking.
- Automatically executing instructions.
- Replacing explicit proposal and authorization boundaries.

# Required tests

- Unlisted instruction source is ignored and diagnosed.
- Malformed typed instruction is rejected.
- Scope and path applicability are enforced.
- Higher-authority instructions remain distinguishable from local guidance.
- `art` does not match `heart` in exact lexical mode.
- Unicode words and punctuation tokenize deterministically.
- Title, description, path, and body weights are independently observable.
- Equal scores use stable path-based tie-breaking.
- Context-pack output explains why each result and instruction was included.
- Existing ordinary queries retain deterministic results where token semantics
  are unchanged.

# Acceptance criteria

- Every included instruction originates from a validated allowlisted source.
- Context packs expose instruction identity, authority, scope, and applicability.
- Exact lexical mode has no incidental substring matches.
- Ranking evidence is sufficient to reproduce the score without hidden state.
- Invalid instructions and evidence gaps are surfaced, not silently discarded.

# Validation commands

```bash
pytest tests/context tests/cli/test_context_cli.py
pytest
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-002: Deterministic facts and semantic interpretation are separate
- DD-010: Explicit instruction allowlist
- DD-014: Context packs use multiple retrieval modes
- DD-015: Knowledge gaps use evidence signals
- DD-016: Adversarial review is selective
