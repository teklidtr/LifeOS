---
id: LIFEOS-1727
title: Share the status projection with doctor without an internal JSON round-trip
status: completed
phase: hardening
depends_on: []
risk: low
---

# Goal

Remove the unnecessary status-to-JSON-to-dictionary conversion inside doctor by sharing the existing status projection directly, with unchanged public JSON and text output.

# Problem evidence

At planning HEAD `2996540ee16f574503b4226baa417bf55fea380c`, `src/lifeos/status.py:serialize_status_json` built the status dictionary and immediately serialized it. `src/lifeos/doctor.py:serialize_doctor_json` reconstructed that dictionary with `json.loads(serialize_status_json(result.vault_status))` before serializing the outer doctor object. The round-trip was an internal composition step, not persistence, hashing, canonicalization, or IPC.

# Scope

- Extract the existing status dictionary projection into one small ordinary helper owned by `status.py`.
- Have both `serialize_status_json` and `serialize_doctor_json` consume that helper; keep serialization at each actual public JSON boundary.
- Remove only imports and intermediate conversion code made unused by this change. Preserve the public serializer signatures and return types.

# Out of scope

- Recovery-readiness collection, status collection, a general serialization framework, new result models, or repository-wide JSON cleanup.
- Proposal byte validation, persistence/hashing round-trips, bridge JSON conversion, and transport-specific representations.

# Required invariants

- Preserve every status/doctor JSON key and value, object/array shape, null/default handling, proposal status mapping, deterministic key order, indentation/escaping, and error behavior.
- Preserve CLI/text output, sanitized diagnostics, readiness decisions, and public return types. The helper must not add collection work or expose additional fields.

# Acceptance criteria

- [x] Doctor composes the status projection directly without serializing/parsing its nested status value.
- [x] Both public serializers use one status projection, with no duplicated dictionary construction or new serialization abstraction.
- [x] Existing status and doctor output tests pass. Representative before/after serialized output was compared byte-for-byte for unavailable/empty and populated status projections, including proposal zero counts, and for the nested doctor `vault` projection.
- [x] Existing behavioral tests remain unchanged; no helper-mirroring test was added because existing status/doctor coverage plus byte-for-byte compatibility checks cover the behavior boundary.
- [x] The internal `serialize_status_json -> json.loads` intermediate representation was removed. The refactor is intentionally small rather than reported as a large code reduction.

# Documentation impact

Status: none
Reason: This internal projection-sharing cleanup preserves public CLI/JSON/text formats, collection behavior, readiness semantics, and capability discovery. No documented user or architecture contract changed.

# Validation

```bash
uv run pytest -q tests/status
uv run pytest -q tests/cli -k doctor
uv run ruff check src/lifeos/status.py src/lifeos/doctor.py
uv run ruff format --check src/lifeos/status.py src/lifeos/doctor.py
uv run mypy src
python scripts/validate_tasks.py
```

Run checks for any directly affected tests as well. Follow root `AGENTS.md` if a changed shared/public seam requires broader validation; do not expand this task merely to perform neighboring cleanup.

# Validation results

- A direct local checkout was attempted, but this execution environment could not resolve `github.com`; local repository commands were therefore unavailable.
- Pre-CI compatibility audit searched repository callers/patch points for `serialize_status_json`, confirmed no doctor test depended on that old patch seam, and compared representative status and doctor JSON byte-for-byte without normalizing formatting.
- An earlier Codex sandbox validation of the same production refactor after applying the current formatter reported `28 passed` for `uv run pytest -q tests/status` and `106 passed, 43 deselected` for `uv run pytest -q tests/cli -k doctor`. The sandbox mutation was not used to modify this branch; the formatter fix was independently applied by the implementation agent.
- PR #63 `fast-checks` run `34012851292` passed on head `8a53bf11c1a99b3a4a2452fd40dd24fea65a8914`, including task workflow validation, documentation-impact validation, Ruff, mypy, compilation, test collection, and project contract smoke tests.
- The separate `obsidian-plugin` checkpoint passed on the same head, including lint, typecheck, tests, and build.
- Normal `@codex review` reviewed implementation commit `941bc5c9134c58bd441b059334f7f7e95fbb70ed` and reported no major issues. The only subsequent production-file change was the mechanical current-Ruff formatter commit `8a53bf11c1a99b3a4a2452fd40dd24fea65a8914`; repository policy does not require another Codex review for that trivial formatting-only fix.
- Security review was skipped per the user's explicit instruction for LIFEOS-1727.
- Final full-validation run `34012873601` passed on `8a53bf11c1a99b3a4a2452fd40dd24fea65a8914`, including all full pytest shards plus `docker-setup-e2e` clean-room MCP, home-node container, and ARM64 image validation.

# Relevant design decisions

- DD-033 and the status/recovery sections of `docs/architecture.md`: status reports derived state without becoming a new authority.

# Implementation size and sequencing

Extra small. Independent of LIFEOS-1729 because it changes projection composition rather than recovery behavior. The implementation stayed standalone and did not absorb neighboring cleanup.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-luna`, reasoning effort `medium`.
- **Reason for the recommendation:** This is a small, localized extraction with straightforward output equivalence checks. Luna is sufficient; medium reasoning covers serialization type/ordering details without using a stronger model for mostly mechanical work.
