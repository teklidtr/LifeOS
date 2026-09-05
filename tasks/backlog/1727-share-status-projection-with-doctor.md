---
id: LIFEOS-1727
title: Share the status projection with doctor without an internal JSON round-trip
status: backlog
phase: hardening
depends_on: []
risk: low
---

# Goal

Remove the unnecessary status-to-JSON-to-dictionary conversion inside doctor by sharing the existing status projection directly, with unchanged public JSON and text output.

# Problem evidence

At planning HEAD `2996540ee16f574503b4226baa417bf55fea380c`, `src/lifeos/status.py:serialize_status_json` builds the status dictionary and immediately serializes it. `src/lifeos/doctor.py:serialize_doctor_json` reconstructs that dictionary with `json.loads(serialize_status_json(result.vault_status))` before serializing the outer doctor object. The round-trip is an internal composition step, not persistence, hashing, canonicalization, or IPC.

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

- [ ] Doctor composes the status projection directly without serializing/parsing its nested status value.
- [ ] Both public serializers use one status projection, with no duplicated dictionary construction or new serialization abstraction.
- [ ] Existing status and doctor output tests pass. Compare representative before/after serialized output, including empty/populated status and proposal counts, without normalizing away observable formatting changes.
- [ ] Existing behavioral tests remain; add only a missing meaningful output-compatibility case if needed, not a test that merely mirrors helper implementation.
- [ ] Record the removal of one intermediate representation; a LOC-neutral extraction is acceptable and should not be reported as a large code reduction.

# Documentation impact

Status: none
Reason: This internal projection-sharing cleanup preserves public CLI/JSON/text formats, collection behavior, readiness semantics, and capability discovery. No documented user or architecture contract changes; re-evaluate this declaration if implementation expands beyond that boundary.

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

# Relevant design decisions

- DD-033 and the status/recovery sections of `docs/architecture.md`: status reports derived state without becoming a new authority.

# Implementation size and sequencing

Extra small. Independent of LIFEOS-1719 because it changes projection composition rather than recovery behavior; coordinate any concurrent edits to `doctor.py`. Keep it standalone because task rules favor bounded scope and do not require bundling unrelated cleanup.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-luna`, reasoning effort `medium`.
- **Reason for the recommendation:** This is a small, localized extraction with straightforward output equivalence checks. Luna is sufficient; medium reasoning covers serialization type/ordering details without using a stronger model for mostly mechanical work.
