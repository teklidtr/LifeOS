# Implementation Strategy

Use both a comprehensive project brief and granular implementation tasks.

The brief teaches what LifeOS is. Task files control how it is built.

Prefer vertical slices over disconnected horizontal layers. The first end-to-end target is:

```text
study source
  ↓
registered and hashed
  ↓
proposal generated
  ↓
approved
  ↓
validated patch applied
  ↓
index and provenance updated
```

Only Phase 0 and Phase 1 are decomposed in detail. Later phases remain milestones until implementation teaches us more.

## Direction 6: personal experiments

Direction 6 is implemented as eight separately committed vertical slices:
architecture and tasks; canonical artifacts; design, safety, and schedules;
observations, analysis, and history; reviews and proposals; bridge methods;
Obsidian workspace; and migration, privacy, recovery, documentation, and release
validation.

The release gate runs focused and full Python regressions, all Obsidian tests,
plugin lint/typecheck/build, manual link validation, bridge capability and schema
checks, provider-neutrality checks, lifecycle and recovery end-to-end fixtures,
migration interruption and stale-source fixtures, runtime deletion/rebuild,
unsafe blocking, missing-data behavior, and clean-tree/provider-file checks. The
canonical Markdown is also opened directly in tests to verify plugin-independent
portability and human annotation preservation.
