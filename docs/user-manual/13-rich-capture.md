[← Personal Experiments](12-personal-experiments.md) · [Manual home](README.md)

# Rich Capture for Meals, Exercise, and Attachments

Rich capture is the fast doorway from real life into LifeOS. Save the original
observation first, then add structure only when it is useful. A capture can be a
sentence, a meal photo, a workout summary, a receipt, a PDF, an audio note, a
screenshot, or an unsupported file that you simply want to preserve and link.

The feature remains useful without an AI provider. Canonical Markdown, original
files, local metadata and text extraction, explicit links, review surfacing,
deterministic search representations, proposals, and recovery all work locally.

## What is available in this build

Direction 7 contains a broad provider-neutral domain model, but not every planned
entry point or enrichment adapter is wired into the standard Obsidian plugin yet.
This distinction matters when reading the rest of the chapter.

| Surface | Current availability |
|---|---|
| Canonical capture creation, reading, editing, lifecycle transitions, filtering, linking, merge, split, proposal preview, privacy preview, migration preview, and rebuild | Implemented in the Python bridge |
| Original-file import, SHA-256 deduplication, manifests, integrity audits, reference removal, local extraction jobs, cancellation, and retry | Implemented in the Python bridge |
| Ribbon entry, command-palette entry, quick meal, quick exercise, selected-text capture, and opening an active capture note | Registered by the standard plugin |
| Clipboard paste, drag and drop, folder drop, mobile share, and launch buttons embedded in reviews, experiments, conversations, goals, plans, tasks, habits, or diary notes | Represented by workspace origin contracts, but require a host adapter or additional UI wiring |
| OCR, transcription, image descriptions, model nutrition estimates, and provider-backed meal or exercise interpretation | Provider-neutral contracts and privacy boundaries exist, but the standard bridge processing button currently runs local extraction only |
| Timeline, gallery, queues, and chart models | Typed controller and bridge models exist; visible controls depend on the host renderer used by the plugin build |

The standard command list is:

- **Open Rich Capture**
- **Quick Capture Meal**
- **Quick Capture Exercise**
- **Capture Selected Text**
- **Open Active Rich Capture**

**Capture Selected Text** copies the selection into the draft description. In the
current bridge path, it does not automatically create a provenance link to the
source note. Add that link explicitly when the source relationship matters.

## Open the workspace

Use the **Rich Capture** camera ribbon icon for the primary entry point. The
command palette can open the general workspace or start a meal or exercise draft.
When a canonical note under `captures/` is active, **Open Active Rich Capture**
loads it into review mode.

The workspace controller has two main modes:

- **Quick capture** asks only for enough information to save safely. The draft
  supplies a default title, so a sentence alone is enough.
- **Review** exposes the canonical record, attachment integrity, extraction and
  suggestion status, links, duplicate handling, privacy disclosure, and proposal
  actions supported by the host renderer.

Timeline, gallery, list, meal, exercise, attachment, unresolved, failed, and
archived modes are rebuildable projections over canonical records. A plugin build
may expose only a subset of these controls even though the controller supports all
of their states.

## Save first, enrich later

A low-friction capture follows this order:

1. Select `meal`, `exercise`, `attachment`, or `mixed`.
2. Add a short description and optionally adjust the event time. The event time
   must include a timezone; the plugin defaults to the system timezone.
3. Save. LifeOS writes canonical Markdown before optional processing begins.
4. Attach one or more regular files. Original bytes are copied into the vault and
   verified against their source hash.
5. Run local extraction now or later.
6. Review suggestions, links, integrity warnings, and follow-up proposals.

Interrupted or unavailable processing does not erase the capture. You may cancel,
retry, or continue using the original record.

The processing-job state and the capture lifecycle are related but distinct. A
cancelled job remains recorded as cancelled. In the current implementation, the
capture may remain in `processing` until processing is retried or a lifecycle
transition is applied explicitly.

## What information a capture exposes

The canonical note and review workspace should make these user-relevant fields
inspectable:

| Information | Meaning |
|---|---|
| Stable ID and schema version | Identifies the record independently of its title |
| Title and capture type | Human label and domain: meal, exercise, attachment, or mixed |
| Capture time and event time | When the note was saved versus when the event occurred |
| Timezone and source entry point | Interpretation of event time and how capture began |
| Description and user annotations | Original user-owned account and free-form notes |
| Lifecycle state and history | Current state, prior transitions, timestamps, and reasons |
| Privacy scope and sensitive flag | External-processing policy signals described below |
| Location and tags | Optional user-supplied context |
| Attachment references | Filename, media type, byte size, content hash, manifest, and original path |
| Links | Explicit relationships to other LifeOS artifacts |
| Derived values | Value or range, unit, source, confidence, assumptions, evidence, and decision status |
| Domain data | Meal or exercise structure when supplied or accepted |
| Extraction and enrichment status | Separate processing states for the record |
| Exclusion flags | Semantic retrieval, conversations, reviews, and experiment-analysis eligibility |
| Provenance, merge, and split lineage | Where information came from and how records were repaired |
| Creation, update, and content hashes | Audit and stale-write protection |

The current typed update surface exposes title, description, event time, tags,
location, privacy scope, and the sensitive flag. Capture type and the four
exclusion flags exist in the canonical schema, but the standard Rich Capture
controller does not yet provide dedicated controls for changing them after save.

Changing a title does not rename the existing Markdown path. The stable path keeps
its original slug and capture ID unless a separate, audited move is performed.

## Capture lifecycle

| State | User meaning |
|---|---|
| `captured` | The canonical note is safely stored |
| `processing` | A resumable processing pass has started |
| `needs-review` | A result, warning, failure, or user decision needs attention |
| `enriched` | The processing pass finished; inspect per-attachment results because an unsupported extractor can still report `unavailable` |
| `linked` | The capture has been intentionally connected to another artifact |
| `completed` | The user considers the capture reviewed and complete |
| `failed` | A recoverable capture-level operation failed |
| `archived` | The record is retained but removed from ordinary active flow |

Invalid transitions fail with the allowed targets instead of guessing. Archived
captures can return to `needs-review`. A failed capture can be retried, returned to
`captured`, moved to `needs-review`, or archived. The bridge supports explicit
transitions, but the standard controller does not yet expose every lifecycle
button in its default command set.

## Canonical records and attachment storage

Capture notes live under `captures/YYYY/`. Attachment manifests live under
`attachments/manifests/`, and original bytes use collision-safe, content-addressed
paths under `attachments/originals/`.

Canonical capture Markdown stores identity, timestamps, type, lifecycle, privacy,
user description, links, attachment references, user decisions, provenance, and
human annotations. A manifest stores attachment identity, SHA-256 content hash,
original filename, media type, byte size, canonical vault-relative path, parent
references, lineage, redaction state, provider-disclosure history, and processing
state.

Large binaries are never placed in frontmatter or embedded as base64. Absolute
machine paths are import inputs only and never become canonical. Markdown and
original files remain usable outside the plugin.

Only regular files are accepted by the current attachment store. Directories,
symlinks, devices, and other non-regular inputs are rejected. Folder-drop support
therefore requires a host adapter to enumerate regular files before import.

### Original, extracted, and inferred data

LifeOS keeps these layers separate:

| Layer | Meaning | Durable authority |
|---|---|---|
| Original user statement | What you typed or dictated | Human-owned capture Markdown |
| Original attachment | Exact imported bytes | Content-addressed original file |
| Confirmed metadata | A user-confirmed or corrected field | Canonical capture Markdown with source retained |
| Deterministic extraction | Text or metadata produced locally | Rebuildable result with method, version, and source hash |
| AI interpretation | OCR, transcript, image description, classification, or estimate | Suggested derived result until reviewed |
| Index, preview, chart, thumbnail, embedding | Browsing or processing aid | Disposable runtime state |

Changing original bytes makes dependent extraction, previews, and embeddings
stale. They are never silently treated as current.

Managed refreshes preserve the free-form **User annotations** section. Do not
remove or duplicate the named managed block markers. A malformed or duplicated
managed block is rejected rather than rewritten.

## Adding, removing, and deleting attachments

Exact byte duplicates reuse one canonical original by default. Select an
independent copy only when separate attachment identity and lineage matter.

Removing an attachment from a capture removes only the reference. It does not
delete the manifest or original bytes. The underlying storage service can delete
an original only after confirming that no capture references it, but the current
standard bridge and workspace do not expose that destructive operation. This is a
conservative limitation, not automatic garbage collection.

Likewise, the standard workspace does not currently expose a direct capture-delete
operation. Archive the capture when you want to remove it from active views while
preserving evidence. Manual deletion should be followed by a rebuild and orphan
review.

## Meal and drink capture

A meal may be recorded with only a photo or sentence. Optional details include
meal type, components, approximate portions, preparation, context, hunger,
fullness, satisfaction, symptoms or observations, recipe links, diary links,
review links, and experiment links.

Calories and macronutrients are optional. `unknown` and `not tracked` are valid
outcomes. Meal views avoid moral labels and do not frame ordinary capture around
weight loss.

The meal schema can preserve foods, portions, preparation, subjective context,
and nutrition values. The standard plugin currently saves the basic capture and
attachments; richer structured meal entry or automatic image interpretation
requires additional UI or provider wiring.

### Nutrition uncertainty

Every nutrition value retains its source:

- user entered,
- food-label derived,
- database derived,
- recipe calculated,
- image estimate,
- language-model estimate,
- unknown.

An estimate can use a range, unit, confidence category, assumptions, and evidence
references. Confirming an estimate changes its decision status but does not
rewrite its source to `user-entered`. Correcting it records `corrected` while
retaining the original provenance category.

An ambiguous photo should produce a broad range or remain unknown, not a falsely
precise calorie number. Potential allergens from an image or model are uncertain
possibilities, never proof.

Rich capture does not diagnose allergies, deficiencies, intolerances, or eating
disorders. Urgent descriptions such as breathing difficulty, throat closing,
swollen tongue, fainting, severe dehydration, or vomiting blood stop normal
enrichment and display immediate-safety guidance. Less urgent concern phrases
produce a caution rather than a diagnosis.

## Exercise and activity capture

Exercise captures support strength training, running, walking, cycling, mobility,
combat sports, classes, sports, rehabilitation-style observations, and
unstructured activity. A capture can include start and end time, duration, sets,
repetitions, load, distance, pace, heart rate supplied by the user, exertion,
rest, sequence, energy, enjoyment, discomfort, notes, and deviations from a plan.

The deterministic no-provider parser recognizes only explicit information and a
small set of common activity names. It does not infer a completed workout from a
scheduled time or invent missing duration, load, distance, or heart rate.

### Planned versus performed activity

LifeOS keeps these outcomes distinct:

- planned,
- performed,
- partial,
- skipped,
- modified,
- imported,
- inferred.

A scheduled time passing never marks a workout complete. A performed capture may
link back to the plan while preserving what changed. Updating the plan, task,
habit, goal, or schedule requires a proposal; recording what happened does not.
Unknown duration or load stays missing rather than appearing as zero on a chart.

The workspace does not diagnose injuries or prescribe treatment. Descriptions of
chest pain, fainting, serious breathing difficulty, sudden weakness, loss of
feeling, or severe injury stop ordinary enrichment and surface urgent guidance.
Sharp pain, numbness, tingling, dizziness, or a joint giving way produce a caution.

## General attachments

General captures can preserve receipts, invoices, screenshots, labels, book
pages, diagrams, whiteboards, handwritten notes, forms, reports, tickets,
warranties, audio notes, object photos, and source material for knowledge notes.

Unsupported formats are still preservable, hashable, linkable, searchable by
metadata, archivable, and recoverable. Unsupported processing does not mean
unsupported capture. Short video is preserved as an attachment and metadata when
full processing is unavailable.

## Local extraction, OCR, and transcription

The current local extractor uses these rules:

| Input | Current deterministic behavior |
|---|---|
| UTF-8 `text/*`, Markdown, TXT, CSV, JSON, YAML, and YML | Reads text up to the default 2,000,000-byte extraction limit |
| PDF | Uses optional `pypdf` when available, keeps page markers, and reports medium quality; encrypted PDFs remain preserved but unavailable for local extraction |
| PNG | Records format, width, and height |
| JPEG and other images | Records basic format and byte-size metadata; no local OCR |
| WAV | Records duration, sample rate, and channel count |
| Other audio | Records basic format and byte-size metadata; no local transcript |
| Unsupported or non-UTF-8 content | Preserves the original and reports `unavailable` or `failed` |

The project currently does not declare `pypdf` in `pyproject.toml` or the lockfile.
Without it, PDF files remain safely stored and local PDF text extraction reports
`unavailable`. Install and lock a compatible parser in the same Python environment
before relying on PDF extraction.

OCR, transcription, image interpretation, and provider-backed nutrition or
exercise enrichment have provider-neutral contracts, schema validation, timeout,
redaction, and fallback boundaries. They are not currently exposed as a complete
standard-plugin execution flow. The privacy preview can show what would be sent,
but previewing does not upload anything.

Extracted text is stored separately from the original, with method, version,
source hash, source locator, quality, status, and warnings. Manual corrections do
not discard the original recording or document. Extracted text does not
automatically become a knowledge note; use a reviewed proposal.

## Privacy scopes and protected content

Rich captures may contain sensitive photos, documents, meal observations, or
voice notes. The current scopes do not all mean the same thing:

| Setting | Current effect |
|---|---|
| `standard` | Normal local processing and eligibility rules |
| `private` | A visible canonical privacy classification; the current capture filter does not yet filter by it, and it is not equivalent to protected default-deny |
| `protected` | External processing requires explicit operation scope, and semantic representation is default-denied |
| `sensitive: true` | Uses the same external-processing and semantic-representation default-deny as `protected` |

Provider previews use the vault's canonical `system/retrieval-policy.yml`. An
excluded path never enters the payload. A protected capture, attachment, or
explicitly selected neighboring note can enter an external payload only when the
current request grants that protected scope and the path also matches
`external_allowed_prefixes`. Links are never traversed automatically.

Before any provider operation, the workspace can preview:

- the requested operation,
- exact selected files and text,
- whether each item is text, metadata-only, or original binary,
- bounded excerpts and redactions,
- omitted sources and reasons,
- total included bytes and truncation,
- whether the operation is local-only.

The default privacy-preview budget is 8,000 bytes per item and 24,000 bytes total.
An operation that requires original binary transfer is omitted when the selected
file exceeds the remaining budget.

Attaching a file is not consent to upload it. Previewing a payload is not consent
to send it. Linking a capture does not authorize neighboring diary, health, or
private notes.

The canonical schema includes independent exclusions for semantic retrieval,
knowledge conversations, reviews, and experiment analysis. The current helpers
enforce semantic, conversation, review, and experiment exclusions. A
conversation-excluded capture may still produce a representation for another
approved local semantic use, but the exclusion remains attached to that
representation and the conversation evidence boundary rejects it. Protected or
sensitive captures are denied before semantic representation regardless of the
separate semantic flag. The Rich Capture controller does not expose dedicated
toggles.

## Duplicate files, duplicate captures, merge, and split

Exact byte duplicates are detected by content hash. They may reuse one canonical
original while preserving every capture reference. The same filename with
different bytes is stored separately. You can deliberately request an independent
copy when separate lineage matters.

Visual or semantic similarity is only a suggestion. It never proves that two
meals, screenshots, or workouts are duplicates.

Merge preview shows source hashes, attachments, links, warnings, preservation
behavior, and a server-computed fingerprint over those exact fields. Application
recomputes the preview from canonical Markdown and fails if a source or preview
field changed. A merge creates a new capture, copies every source annotation into
a **Merged source annotations** section, records `merged_from`, and archives the
sources. The merged capture keeps the most restrictive source privacy scope,
becomes sensitive if any source is sensitive, and retains the union of all four
retrieval exclusions, tags, attachments, and links.

Split requires at least two non-empty attachment groups. Duplicate assignments and
unknown attachment IDs are rejected before anything is written. It creates the new
records, records `split_from`, preserves the source privacy, sensitivity, tags,
links, and retrieval exclusions on every child, and archives the mixed source.
The archived source retains its human annotations; LifeOS does not guess which
annotation belongs in which child. Attachments omitted from every split group are
not copied into the new captures, so review the grouping carefully before applying
it.

Merge and split are all-or-nothing canonical transactions. LifeOS prepares every
output and source archive first, checks the exact source hashes again, and then
publishes them as one recoverable file set. A handled storage failure restores the
pre-operation state. After an interruption, the next merge or split recovers the
unfinished transaction before proceeding. If a later Obsidian edit makes safe
rollback ambiguous, LifeOS preserves that edit and reports `recovery_required`
instead of overwriting it.

The workspace sends one idempotency key with each merge or split. Retrying the
same action returns the original output paths without creating duplicate captures
or lifecycle events. Reusing that key for different input is rejected. LifeOS
proves a retry from matching output lineage and source archive history in canonical
Markdown; a disposable cache record alone is never treated as proof that the
operation completed.

## Links, retrieval, and knowledge conversations

A capture may link to goals, plans, tasks, habits, metrics, experiments, diary
entries, reviews, knowledge notes, knowledge conversations, and other captures.
Duplicate identical links are suppressed. Link suggestions remain optional and
inspectable.

Semantic retrieval indexes approved text and metadata, not raw binary files. The
capture representation can contain the title, description, confirmed or corrected
values, and explicitly supplied current extraction text. Suggested or rejected
values are not included. Search evidence retains capture and attachment
provenance, representation kind, hashes, stale state, and filter metadata.

Knowledge conversations distinguish original text from extracted or confirmed
derived text. Evidence links back to the exact capture and attachment. A stale or
changed source is shown as stale, and a conversation cannot claim visual facts
that are absent from approved textual evidence. The conversation boundary checks
`exclude_from_conversations` independently even after a semantic representation
has been approved for another use.

Current rich-capture indexing is an integration helper rather than an automatic
full-vault ingestion hook. A retrieval workflow must explicitly build and supply
the approved capture representation.

## Daily reviews, weekly reviews, and experiments

Daily review evidence can include each non-excluded capture whose event date
matches the review day. It labels capture type, review-needed state, processing
issues, and unconfirmed suggestions.

Weekly review evidence summarizes meal, exercise, attachment, and mixed capture
counts, captures awaiting review, and extraction issues. It does not create a
meal-quality or exercise-quality score.

These sections are optional and evidence-fingerprinted. An unchanged dismissed
finding stays quiet until its evidence changes. Reviews never become mandatory
meal or exercise questionnaires.

Experiments can link a capture as an observation or supporting evidence. A
capture-derived value can become a measured observation only after the field is
explicitly mapped and its status is `confirmed` or `corrected`. The resulting
observation retains the capture path, capture hash, event time, original source
category, and decision status.

The schema-level exclusions are enforced by the integration helpers, but dedicated
Rich Capture UI toggles and a one-click experiment-mapping flow are not yet wired
into the standard controller.

## From capture to action

Reviewed capture evidence can create proposals for tasks, habits, goals, plans,
knowledge notes, note sections, flashcard candidates, research questions,
reminders, calendar entries, expense integration, or review insights.

The preview shows the target path, operation, source capture ID and hash,
attachment IDs, included actions, excluded actions, and target stale-write guard.
Creating a proposal never applies it automatically. Proposal approval and
application remain separate steps in the ordinary proposal workspace.

## Timeline, gallery, queues, and visualizations

The controller can request list, timeline, gallery, meal, exercise, attachment,
unresolved, failed, and archived modes. The visualization bridge returns:

- timeline points with canonical paths,
- counts by capture type and lifecycle state,
- activity-calendar counts,
- extraction and enrichment status counts,
- exercise duration and distance trends,
- experiment links,
- explicit missing-data counts,
- bounded-view warnings.

The default visualization limit is 500 matching captures. The accepted range is
1 to 5,000. Unknown values are omitted and counted as missing rather than plotted
as zero. A rendering failure must not block list view or opening canonical
Markdown.

Selection state can be passed as evidence-only capture paths to another workspace.
Bulk linking, bulk archiving, and one-click conversation or experiment launch from
that selection are not yet implemented by the standard Rich Capture controller.

## Mobile, offline, paste, and drag behavior

The controller defines a one-column mobile state, a 44-pixel minimum touch target,
and deferred enrichment. Canonical saving itself is local and does not wait for a
model response.

Camera import, clipboard paste, drag and drop, folder drop, mobile share, URI
entry, and interrupted-draft recovery depend on the Obsidian host adapter. The
standard plugin registers the `mobile-share`, `paste`, `drag-drop`, and related
origin names in its controller contract, but does not yet register platform event
handlers for all of them. On mobile, the broader LifeOS Python engine may also be
unavailable, so ordinary Markdown capture remains the fallback.

## Accessibility and keyboard controls

The controller exposes visible status text, focus targets, non-color-only states,
descriptive attachment labels, one-column mobile state, and screen-reader-oriented
announcements.

Its action contract defines these mnemonic labels:

| Key | Action |
|---|---|
| `S` | Save original capture |
| `A` | Attach files |
| `R` | Review |
| `P` | Start optional processing |
| `L` | Link another artifact |
| `F` | Preview follow-up proposal |
| `M` | Open canonical Markdown |
| `O` | Open selected original attachment |

These are controller metadata, not global shortcuts guaranteed by every renderer.
Use them only when your plugin build displays or binds them. Tab, Shift+Tab,
Enter, Space, Escape, focus restoration, live announcements, and reduced-motion
behavior likewise depend on the host renderer implementing the controller
contract.

## Degraded states

The workspace names failures instead of hiding them:

- empty or incomplete capture,
- unsupported or oversized processing,
- exact duplicate,
- missing or changed attachment,
- malformed or unsupported-schema artifact,
- queued, cancelled, interrupted, failed, or unavailable extraction,
- OCR, transcription, index, or provider unavailable,
- provider timeout or malformed output,
- sensitive content blocked,
- stale capture, extraction, embedding, proposal, or merge preview,
- migration required,
- storage write failure or path collision.

A stale write means the canonical note changed after the workspace loaded it.
Reload and compare rather than overwriting the newer version. A changed original
means the bytes no longer match the manifest hash; LifeOS does not silently adopt
the new bytes.

The original capture and attachment remain intact unless they were manually
removed outside LifeOS. Open the canonical record, audit attachment integrity,
retry optional processing, or rebuild derived state.

## Migration, rebuilding, and recovery

No repository-defined legacy rich-capture format existed when Direction 7 was
introduced, so the current migration preview is an audited no-op. LifeOS does not
invent a legacy format. Future migrations must preserve source files, source
hashes, timestamps, links, and human annotations and must fail closed when sources
change.

You can delete `.lifeos/captures/` and rebuild the capture index, missing manifests
when enough canonical evidence exists, extraction state, galleries, timelines,
and other derived views. Rebuilds are bounded, checkpointed, resumable, and report:

- malformed or unsupported capture notes,
- duplicate stable identities,
- moved capture paths,
- missing manifests,
- missing or changed originals,
- stale extraction,
- orphan manifests,
- orphan original files.

A rebuild can be interrupted and resumed without changing canonical Markdown or
original bytes. Rebuilding a manifest requires an unchanged original plus enough
information in a capture reference. Human-owned Markdown is not rewritten merely
to refresh a view.

## Current implementation limitations

The most important current limitations are collected here so architectural
capability is not mistaken for a finished UI action:

- Provider-backed OCR, transcription, image descriptions, meal recognition, and
  nutrition estimation are not wired as standard plugin actions.
- The standard processing action runs deterministic local extraction for all
  attachments on the loaded capture; it does not select a subset.
- Changing capture type after save is not exposed by `capture.update`.
- Dedicated controls for semantic, conversation, review, and experiment
  exclusions are not exposed by the standard controller. The conversation-only
  flag is also not independently enforced by the current evidence helper.
- Direct capture deletion and unreferenced-original deletion are not exposed by
  the standard bridge. Reference removal and archive are the safe user-facing
  actions.
- Paste, drag, drop, folder import, mobile share, and context-specific launch
  buttons require host wiring beyond the registered standard commands.
- Selected-text capture does not automatically link the source note.
- Timeline, gallery, queue, visualization, and keyboard state models require a
  renderer that turns controller state into visible controls.
- Rich-capture retrieval and experiment mapping exist as integration helpers,
  not automatic full-vault pipelines.

These limitations do not weaken the canonical storage guarantees. The notes,
manifests, original bytes, hashes, and human annotations remain portable and
inspectable while the UI surface grows around them.

[← Personal Experiments](12-personal-experiments.md) · [Manual home](README.md)
