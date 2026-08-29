[← Obsidian Desktop](06-obsidian-desktop.md) · [Manual home](README.md) · [Next: Adaptive Planning →](08-adaptive-planning.md)

# Troubleshooting, Upgrades, and Removal

## Connection states

- **Unavailable:** verify the configured Python path and `lifeos.yml` path.
- **Incompatible:** update either the plugin or Python package. No writes are attempted.
- **Stale:** reload the note and compare the concurrent Obsidian edit before retrying.
- **Blocked:** complete the displayed recovery or authorization step.
- **Corrupt:** open the linked canonical note and repair the typed diagnostic.

## Ingestion command is unavailable

This is expected: the standalone `lifeos ingest` command and embedded model
runtime were removed. Connect an external agent to the local `lifeos-mcp` STDIO
server and let the agent work through the bounded MCP tools instead. LifeOS does
not need a model name or provider API key for ingestion.

For current durable-Wiki ingestion, the preferred flow is:

```text
registry_refresh as needed
  → vault_read_markdown on the registered source
  → vault_context when goals, study purpose, instructions, or nearby vault state matter
  → wiki_search
  → vault_read_markdown on relevant wiki hits
  → decide whether durable knowledge should change
  → if no useful durable change exists: create no proposal
  → otherwise ingestion_evolve_wiki_proposal with 1..12 reviewed mutations
  → stop at draft
```

`ingestion_evolve_wiki_proposal` may coordinate generated-page creates and
ownership-aware exact-section updates in one atomic draft. Each mutation has an
explicit target and rationale. Folder structure beneath `wiki/` is allowed to
emerge from the existing knowledge instead of being forced into
`source/entity/concept/synthesis` folders.

The older `ingestion_create_wiki_proposal`,
`ingestion_update_wiki_section_proposal`, and
`ingestion_create_wiki_and_update_section_proposal` tools remain compatibility
surfaces for bounded single/fixed-shape callers, but they are not the preferred
new ingestion workflow. Likewise, `page_kind + slug` typed routing remains
compatible but is no longer recommended as the canonical Wiki organization.

For a registered `study/` source, use `study_evolve_learning_proposal` when the
same reviewed draft should combine Wiki evolution with selective flashcards.
Flashcards are chosen according to the inferred learning context rather than
being generated for every fact. Non-study sources do not receive automatic
flashcards by default.

All proposal-producing ingestion paths stop at draft. Low-level MCP lifecycle
tools still require explicit submit, approve, and apply intent. In Obsidian, the
proposal workspace normally exposes one trusted **Accept changes** confirmation
that performs only the remaining lifecycle transitions while preserving all
hash, digest, ownership, and recovery checks.

Exact-section updates require one unique ATX heading, supplied without `#`
markers. If the heading is missing or duplicated, choose a more precise target
heading or edit the note structure before retrying. Deterministic LifeOS code
does not perform autonomous semantic whole-note merging.

If ingestion reports that a missing target retains generated ownership, do not
edit `system/generated-ownership.json` casually. The file was deleted while its
durable authorization entry remained. Restore the generated file or use an
explicit ownership-release workflow. If the target exists but its ownership hash
or generator differs, reconcile that mismatch before retrying. No invalid draft
is created, and `registry_refresh` does not alter ownership.

Open **LifeOS Proposals** and find the **Ownership recovery** card for the missing
target. Use **Restore instructions** if you can restore reviewed bytes matching the
displayed SHA-256. If deletion was intentional, use **Create release proposal**,
review the `system/generated-ownership.json` deletion diff, and then use **Accept
changes**. If the target reappears or any ownership field changes before
acceptance, LifeOS refuses the stale release proposal. Do not edit the manifest by
hand to bypass review.

If the MCP tools are missing, verify the `mcp` extra is installed in the LifeOS
application environment and that the client launches `lifeos-mcp` with the
intended vault's `lifeos.yml` configuration.

## Expected `wiki/entities/` or `wiki/concepts/`, but they are missing

Those folders are no longer required. LifeOS intentionally does not prescribe a
fixed wiki taxonomy. Current ingestion searches existing knowledge and lets the
agent choose useful targets beneath `wiki/`, such as `wiki/learning/`,
`wiki/people/`, a flat `wiki/`, or another structure that fits the vault.

The old `page_kind + slug` API can still derive `wiki/entities/`,
`wiki/concepts/`, `wiki/sources/`, or `wiki/syntheses/` for compatibility, but
MCP guidance no longer prefers it. Approved generated creates can safely create
missing nested folders beneath an existing `wiki/` root. Draft proposals do not
materialize those folders.

Remember that `raw/` already holds source evidence. A `wiki/sources/` mirror is
usually unnecessary unless you deliberately choose to maintain one as durable
knowledge.

## Registry paths are stale after a file move

Run the supported deterministic refresh from the directory containing
`lifeos.yml`:

```bash
uv run lifeos scan
```

From another directory, pass `--config /absolute/path/to/lifeos.yml`. The command
reports new, modified, unchanged, and deleted paths and refreshes the proposal
index. It changes only disposable `.lifeos/registry.db` state. It does not update
source links written inside Markdown and does not rebuild semantic retrieval;
those require a proposal and **Synchronize index**, respectively.

## Plugin fails to load

Rebuild from the repository root with `npm --prefix packages/obsidian-plugin ci`
and `npm --prefix packages/obsidian-plugin run build`. Copy only `build/main.js`,
`build/manifest.json`, and `build/styles.css` into
`.obsidian/plugins/lifeos/`, then reload Obsidian.

The production `main.js` is a bundled CommonJS Obsidian entry point. Files under
`dist-test/` are unbundled test output and cannot be installed directly. If the
plugin loads but reports **Unavailable**, the plugin bundle is working; correct
the Python executable or `lifeos.yml` path in LifeOS Settings.

## Check recovery readiness with `lifeos doctor`

`lifeos doctor` is a read-only diagnostic. From the vault directory, run:

```bash
uv run lifeos doctor --config lifeos.yml
```

Use `--json` when another UI or script needs stable diagnostic IDs, statuses,
severities, remediation, and exposed relative paths. Recovery diagnostics are
reported separately from ordinary application readiness, so a vault may be
usable while still having a recovery warning.

The recovery section distinguishes three layers:

1. **Canonical Git coverage.** LifeOS checks whether the configured vault is
   covered by Git, whether canonical history has any commit, the latest commit
   that actually touched the configured vault, whether visible committed
   canonical tree entries are ordinary locally **hash-verified** blob objects,
   and current staged, modified, deleted, untracked, or ignored canonical paths.
   Missing or corrupt local blob objects, object-ID mismatches, gitlinks, or
   symlink-style committed entries are reported through
   `recovery.git.canonical_objects` rather than counted as recoverable canonical
   coverage. Canonical paths marked `assume-unchanged` or `skip-worktree` make
   working-tree cleanliness **unknown** until those flags are cleared. If only
   stat-cache metadata changed and content equality cannot be established from
   metadata alone, the path is reported under `working_tree_uncertain_paths` and
   the uncommitted diagnostic is **unknown**, not falsely labeled modified.
   Staging is not a substitute for a commit. An old commit timestamp is
   informational by itself; a clean vault can remain fully represented by an old
   commit.
2. **Independent backup/snapshot evidence.** Local Git history can recover
   committed logical versions, but it can disappear with the same disk. A Git
   remote name or remote-tracking ref does not prove that an off-device copy is
   current. The initial provider-neutral doctor therefore reports
   `recovery.backup.external` as **unknown / not verified** unless LifeOS has
   deterministic evidence. Unknown means LifeOS cannot prove the backup state; it
   does not mean that your backup system is absent or broken.
3. **Disposable runtime.** `.lifeos/registry.db`, activity logs, indexes,
   graph/export generations, caches, and other derived runtime state are not
   canonical recovery material. Their absence from Git is not a recovery gap.
   Restore canonical files first, then rebuild the runtime state. Do not solve a
   doctor warning by committing `.lifeos/`.

Protected or policy-excluded canonical paths are never named in recovery output.
Because the current doctor has no explicit protected-scope authorization input,
checks whose completeness depends on such hidden scope report **unknown /
incomplete** rather than `pass`. This preserves nondisclosure without turning
uninspected sensitive data into a false clean signal.

Typical actionable Git warnings name only the relative paths needed to fix the
problem. Git repository inspection failures are reported as **unknown** rather
than being confused with a vault that has no repository. Recovery queries disable
Git features that can execute configured filesystem monitors or content filters,
strip inherited repository-selection variables, avoid lazy object fetching, and
hash-check committed blob payloads without copying their contents into diagnostic
output. The doctor does not copy note bodies or secrets into recovery output and
does not commit, push, restore, scan, repair, or create backups for you.

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
