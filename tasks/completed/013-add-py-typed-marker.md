---
id: LIFEOS-013
title: Publish LifeOS typing metadata
status: completed
milestone: phase-0-project-skeleton
depends_on: []
affected_paths:
  - src/lifeos/py.typed
  - pyproject.toml
risk: low
---

# Goal

Make installed LifeOS packages advertise their inline type information to external mypy runs.

# Scope

- Add and package a PEP 561 `py.typed` marker.
- Verify editable and wheel installations include the marker.
- Confirm mypy can analyze consumers without an `import-untyped` error.

# Out of scope

- Registry schema changes
- New type-checking tools or configuration rewrites
- Generating separate stub packages

# Acceptance criteria

1. The built LifeOS package includes `lifeos/py.typed`.
2. Mypy recognizes installed LifeOS modules as typed.
3. Existing source and test type checks continue to pass.

# Validation

```bash
python -m build
mypy src tests
```

# Relevant decisions

- `docs/roadmap.md#phase-0-project-skeleton`

**Implementation completed.**
* implementation commit hash: 91e1c87ab1dff86c6b61a8467193a5cf83121042
* wheel contains `lifeos/py.typed`
* source distribution contains `src/lifeos/py.typed`
* external installed mypy consumer sees the real callable type
* full tests passed
* mypy passed
* Ruff passed
* explicit package-data configuration was NOT necessary
