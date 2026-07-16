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

## Recovery hatch

The vault remains ordinary Markdown when the plugin is unavailable. You may edit notes in
Obsidian normally and use the CLI only for diagnosis, rebuilding, or recovery.

[← Obsidian Desktop](06-obsidian-desktop.md) · [Manual home](README.md) · [Next: Adaptive Planning →](08-adaptive-planning.md)
