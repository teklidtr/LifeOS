---
id: LIFEOS-800
status: completed
phase: 9
title: Purpose-specific optional exports
---

## Goal

Generate explicit, purpose-specific bundles under `.lifeos/exports/` without creating a second canonical vault.

## Scope

- Support public wiki, study, trusted-agent, and personal-review bundles.
- Select source areas per export purpose.
- Preserve relative paths and record source hashes in a manifest.
- Exclude private notes from public exports.
- Add `lifeos export build` text and JSON output.

## Out of scope

- Continuous mirrored synchronization.
- Uploading or publishing bundles.
- Editing canonical Markdown.

## Acceptance criteria

- Exports require the exports feature flag.
- Repeated builds are deterministic.
- Manifests identify every source and content hash.
- Export output lives only under the runtime directory.
- Unit and CLI tests pass.
