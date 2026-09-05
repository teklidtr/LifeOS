# Rich Capture Testing and Release Validation

Rich capture uses deterministic unit, bridge, plugin, and end-to-end fixtures.
The suite covers canonical round trips, managed-block preservation, lifecycle and
stale writes, content hashing and duplicate handling, extraction and cancellation,
meal and exercise uncertainty, safety messages, retrieval representations,
knowledge evidence, review sections, experiment mappings, proposals, privacy,
migration, recovery, visualizations, and workspace accessibility.

`./scripts/validate-rich-capture.sh` is retained as a focused local Rich Capture
regression helper and is called from this document. It is not a repository release gate
and does not replace the merge-readiness contract in `AGENTS.md` and `README.md`.
Repository release readiness is established by the current `fast-checks`,
`obsidian-plugin`, and explicit `full-validation` CI checkpoints, which cover the
complete package, plugin, pytest, setup, home-node, and ARM64 surfaces.

## Focused commands

```bash
PYTHONPATH=src python3 -m pytest --import-mode=importlib \
  tests/captures tests/bridge/test_capture_bridge.py \
  tests/e2e/test_rich_capture.py -q

npm --prefix packages/obsidian-plugin run lint
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build

python3 scripts/validate_manual_links.py
./scripts/validate-rich-capture.sh
```

## Required invariants

Tests assert that original bytes survive processing and runtime deletion; canonical
Markdown remains the source of truth; human annotations survive managed refresh;
unknown and missing values do not become zero; estimates remain sourced and
separate from confirmed values; captures save when enrichment fails; protected
content is not disclosed; external mutations remain proposals; provider-specific
fields do not leak into public contracts; and indexes, extractions, previews, and
visualizations are rebuildable.

Large-collection fixtures use bounded batches and interrupted rebuild checkpoints.
Quiet test output is preferred. Binary data, generated bundles, and full provider
payloads are not printed to logs.
