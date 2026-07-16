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

## Direction 7: rich capture

Direction 7 is delivered as nine separate commits: architecture and task design;
canonical captures and manifests; storage, extraction, lifecycle, merge and split;
meal and exercise semantics, enrichment, and safety; retrieval, conversation,
review, experiment, and proposal integration; bridge capabilities; Obsidian
workspace; privacy, migration, and recovery; and final visualizations,
documentation, validation, reports, and packaging.

The release gate validates canonical portability, original-byte preservation,
hash deduplication, same-name different-content handling, local and unavailable
extraction, no-provider and timeout behavior, protected-scope denial, nutrition
uncertainty, plan-versus-performance semantics, retrieval and conversation
provenance, review and experiment integration, stale proposal protection,
runtime deletion and rebuild, manual links, bridge capabilities, plugin tests,
type checking, linting, and production build.
