---
id: LIFEOS-116
status: completed
---

# LIFEOS-116: Read-only file comparison

## Goal
Provide a read-only comparison API that determines current new, modified, unchanged, and missing files against the registry without persisting the scan.

## Requirements
* Streams current vault hashes.
* Compares against registered hashes using a read-only registry connection.
* Returns `ScanResult` or an equivalent model detailing `new`, `modified`, `unchanged`, and `missing`/`deleted` paths.
* Performs no registry writes.
* Remains separate from `register_scan()`.

## Completion Evidence
* implementation commit hash: 963a71b
* final focused and full-suite counts: 11 focused comparison tests, 377 full suite.
* Ruff passed.
* mypy passed.
* read-only connection never initializes or migrates.
* missing or incompatible registry raises rather than pretending the file is unregistered.
* tombstones are logically unregistered.
* file scans retain bounded-memory streaming.
* exact ingestion bytes use the same canonical SHA-256 implementation.
