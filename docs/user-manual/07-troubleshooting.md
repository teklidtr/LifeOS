[← Obsidian Desktop](06-obsidian-desktop.md) · [Manual home](README.md) · [Next: Adaptive Planning →](08-adaptive-planning.md)

# Troubleshooting, Upgrades, and Removal

## Connection states

- **Unavailable:** verify the configured Python path and `lifeos.yml` path.
- **Incompatible:** update either the plugin or Python package. No writes are attempted.
- **Stale:** reload the note and compare the concurrent Obsidian edit before retrying.
- **Blocked:** complete the displayed recovery or authorization step.
- **Corrupt:** open the linked canonical note and repair the typed diagnostic.

## Safe upgrade

1. Commit or back up the Markdown vault.
2. Stop the LifeOS plugin and optional background service.
3. Replace the plugin files and update the Python package together.
4. Re-enable the plugin and confirm the protocol versions match.
5. Rebuild disposable registry, review, graph, or export state when prompted.

A failed upgrade must not rewrite Markdown. Restore the previous plugin and Python package,
then reopen the same vault.

## Disable or uninstall

Disable the plugin in Obsidian and use **Uninstall background service** in LifeOS Settings.
Removing `.lifeos/` deletes only disposable state. Review progress and history are rebuilt
from `reviews/daily/` and `reviews/weekly/`. Do not delete `system/`, `reviews/`,
`proposals/`, or other canonical vault folders unless you intend to delete their contents.

## Review recovery

Use the review workspace rebuild action after removing `.lifeos/`. A stale review must be
reloaded before refresh. Duplicate identities, unsupported schemas, or damaged managed
boundaries are blocked with a link to the canonical Markdown note. Legacy migration must
be previewed again whenever a source hash changes.

## Semantic retrieval recovery

- **Missing index:** choose **Rebuild index**.
- **Stale index:** choose **Synchronize index** after ordinary note changes.
- **Interrupted rebuild:** resume it; the prior healthy index remains active until publication.
- **Corrupt or incompatible index:** use the displayed recovery plan to delete only `.lifeos/retrieval/` and rebuild.
- **No results:** inspect scope filters, exclusions, protected-path diagnostics, and exact spelling.
- **Unavailable provider:** continue in evidence-only or local retrieval mode.
- **Timeout, cancellation, or malformed response:** no unsupported generated answer is saved as grounded fact.
- **Stale evidence:** open the changed source and rerun retrieval; the historical turn remains preserved.

Deleting `.lifeos/` does not delete `conversations/` or any canonical note. The
next rebuild recreates derived chunks and ranking state from Markdown.


## Recovery hatch

The vault remains ordinary Markdown when the plugin is unavailable. You may edit notes in
Obsidian normally and use the CLI only for diagnosis, rebuilding, or recovery.

## Personal experiment recovery

- **Missing index:** rebuild `.lifeos/experiments/` from canonical experiment Markdown.
- **Interrupted rebuild:** resume from the checkpoint; canonical artifacts are unchanged.
- **Malformed or unsupported artifact:** open the linked Markdown and preserve it until a compatible repair is available.
- **Duplicate identity:** keep both files untouched and resolve the duplicate before rebuilding.
- **Stale artifact:** reload before applying a lifecycle, observation, amendment, or conclusion write.
- **Unsafe protocol:** read the displayed safety classification; blocked protocols cannot be activated.
- **Insufficient evidence:** collect more observations or record an inconclusive conclusion.
- **Provider unavailable:** continue with local design, tracking, analysis, reviews, and proposals.
- **Migration source changed:** create a new preview so the stable source hash can be verified.

Deleting `.lifeos/experiments/` removes only disposable indexes and rebuild
journals. It does not remove experiment Markdown, observations, amendments,
conclusions, or human annotations.


## Rich capture recovery

- **Stale capture or merge preview:** reload the canonical Markdown and rebuild
  the preview before applying a write.
- **Missing attachment:** locate the original or deliberately remove the broken
  reference. LifeOS does not invent replacement bytes.
- **Changed attachment:** review and re-import or relink it; extraction and
  embeddings based on the old hash are stale.
- **Unsupported or oversized extraction:** keep the original and continue without
  processing. The default text and PDF extraction limit is 2,000,000 bytes.
- **PDF extraction unavailable:** the repository does not currently lock
  `pypdf`; install and lock it in the LifeOS environment or preserve the PDF
  without extraction.
- **Cancelled processing:** retry the recorded job. The capture may remain in the
  `processing` lifecycle state until a retry or explicit transition finishes it.
- **Protected content blocked:** inspect the privacy preview and grant exact
  per-operation scope, or stay local-only.
- **Runtime corruption or deletion:** rebuild `.lifeos/captures/` from capture
  Markdown, manifests, and original bytes.
- **Orphan files or manifests:** review the rebuild diagnostics before deleting
  anything. The standard workspace removes references but does not expose
  destructive original-file deletion.

Archive remains the normal safe alternative to deleting a canonical capture.
See [Rich Capture](13-rich-capture.md) for lifecycle, storage, and current UI
limits.

[← Obsidian Desktop](06-obsidian-desktop.md) · [Manual home](README.md) · [Next: Adaptive Planning →](08-adaptive-planning.md)
