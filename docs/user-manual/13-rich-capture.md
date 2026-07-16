[← Personal Experiments](12-personal-experiments.md) · [Manual home](README.md)

# Rich Capture for Meals, Exercise, and Attachments

Rich capture is the fast doorway from real life into LifeOS. Save the original
observation first, then add structure only when it is useful. A capture can be a
sentence, a meal photo, a workout summary, a receipt, a PDF, an audio note, a
screenshot, or an unsupported file that you simply want to preserve and link.

The feature remains useful without an AI provider. Canonical Markdown, original
files, local metadata and text extraction, links, review surfacing, deterministic
search representations, proposals, and recovery all work locally.

## Open the workspace

Use the **Rich Capture** ribbon icon for the primary workspace. You can also open
it from the command palette, an active note or selection, clipboard or pasted
content, a dragged file, a daily or weekly review, an experiment, a knowledge
conversation, or a goal, plan, task, habit, or diary entry.

The workspace has two main modes:

- **Quick capture** asks only for enough information to save safely. A title,
  sentence, or attachment is sufficient.
- **Review** shows the canonical record, attachment integrity, extraction and
  enrichment results, uncertainty, links, duplicate suggestions, and proposal
  actions.

Timeline, gallery, list, meal, exercise, attachment, unresolved, failed, and
archived views are rebuildable projections over canonical records.

## Save first, enrich later

A low-friction capture follows this order:

1. Select a capture type or leave it as a general attachment.
2. Add a short description, paste or drag a file, and adjust the event time when
   it differs from the capture time.
3. Save. LifeOS writes canonical Markdown and preserves original bytes before
   optional processing starts.
4. Review local extraction, OCR, transcription, classification, nutrition, or
   exercise suggestions later.
5. Confirm, correct, reject, link, split, merge, archive, or create a proposal.

Interrupted or unavailable enrichment does not erase the capture. You may cancel,
retry, or continue using the original record.

## Canonical records and attachment storage

Capture notes live under `captures/YYYY/`. Attachment manifests live under
`attachments/manifests/`, and original bytes use collision-safe, content-addressed
paths under `attachments/originals/`.

Canonical capture Markdown stores identity, timestamps, type, lifecycle, privacy,
user description, links, attachment references, user decisions, provenance, and
human annotations. A manifest stores the attachment identity, SHA-256 content
hash, original filename, media type, byte size, canonical vault-relative path,
parent references, lineage, and processing state.

Large binaries are never placed in frontmatter or embedded as base64. Absolute
machine paths are import inputs only and never become canonical. Markdown and
original files remain usable outside the plugin.

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

## Meal and drink capture

A meal may be recorded with only a photo or sentence. Optional details include
meal type, components, approximate portions, preparation, context, hunger,
fullness, satisfaction, symptoms or observations, recipe links, diary links,
review links, and experiment links.

Calories and macronutrients are optional. `unknown` and `not tracked` are valid
outcomes. Meal views avoid moral labels and do not frame ordinary capture around
weight loss.

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
references. Confirming an estimate does not erase its original source. An
ambiguous photo should produce a broad range or remain unknown, not a falsely
precise calorie number.

Potential allergens from an image or model are uncertain possibilities, never
proof. Rich capture does not diagnose allergies, deficiencies, intolerances, or
eating disorders. Urgent descriptions such as a severe allergic reaction or
poisoning stop normal enrichment and display immediate-safety guidance.

## Exercise and activity capture

Exercise captures support strength training, running, walking, cycling, mobility,
combat sports, classes, sports, rehabilitation-style observations, and
unstructured activity. A capture can include start and end time, duration, sets,
repetitions, load, distance, pace, heart rate supplied by the user, exertion,
rest, sequence, energy, enjoyment, discomfort, notes, and deviations from a plan.

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
chest pain, fainting, serious breathing difficulty, neurological symptoms, or an
acute injury stop ordinary enrichment and surface a safety message.

## General attachments

General captures can preserve receipts, invoices, screenshots, labels, book
pages, diagrams, whiteboards, handwritten notes, forms, reports, tickets,
warranties, audio notes, object photos, and source material for knowledge notes.

Unsupported formats are still preservable, hashable, linkable, searchable by
metadata, archivable, and recoverable. Unsupported processing does not mean
unsupported capture. Short video is preserved as an attachment and metadata when
full processing is unavailable.

## Text extraction, OCR, and transcription

Local deterministic extraction supports UTF-8 text and Markdown, basic image and
audio metadata, and bounded PDF text when the optional locked PDF parser is
installed. Encrypted, malformed, oversized, or unsupported documents stay
preserved and receive an explicit degraded state.

OCR and transcription are optional provider-neutral operations. Results record
the method, version, source hash, source page or region when available, quality,
status, and uncertainty. They remain separate from the original. Manual
corrections are visible, and the original recording or document is never discarded.

Extracted text does not automatically become a knowledge note. Use a reviewed
proposal for downstream knowledge changes.

## Privacy and protected scopes

Rich captures may contain sensitive photos, documents, meal observations, or
voice notes. External processing is default deny for protected captures and
sensitive folders.

Before any provider operation, the workspace can show:

- the requested operation,
- exact selected files and text,
- bounded excerpts or binary-transfer scope,
- redactions,
- omitted sources and reasons,
- total payload size,
- whether the operation is local-only.

Attaching a file is not consent to upload it. Linking a capture does not authorize
traversal into neighboring diary, health, or private notes. Captures may be
excluded independently from semantic retrieval, knowledge conversations, reviews,
experiment analysis, and AI processing.

## Duplicate files, duplicate captures, merge, and split

Exact byte duplicates are detected by content hash. They may reuse one canonical
original while preserving every capture reference. The same filename with
different bytes is stored separately. You can deliberately request an independent
copy when separate lineage matters.

Visual or semantic similarity is only a suggestion. It never proves that two
meals, screenshots, or workouts are duplicates.

Merge preview shows source hashes, attachments, links, warnings, and preservation
behavior. Application fails if a source changed after preview and records source
identities and lifecycle history. Split creates new records and archives the mixed
source without deleting evidence.

## Links, retrieval, and knowledge conversations

A capture may link to goals, plans, tasks, habits, metrics, experiments, diary
entries, reviews, knowledge notes, knowledge conversations, and other captures.
Suggestions remain optional and inspectable.

Semantic retrieval indexes only approved text and metadata, not raw binary files.
Eligible representations may include the user description, confirmed fields, and
approved extraction. Search results retain capture and attachment provenance,
representation kind, hashes, stale state, and filter metadata. Duplicate passages
are suppressed.

Knowledge conversations distinguish original text from OCR, transcript, or AI
description. Evidence links back to the exact capture and attachment. A stale or
changed source is shown as stale, and a conversation cannot claim visual facts
that are absent from approved evidence.

## Daily reviews, weekly reviews, and experiments

Daily reviews can optionally surface captures from the day, performed exercise,
failed processing, unreviewed suggestions, and experiment-linked evidence. Weekly
reviews can summarize counts and patterns, deviations, unresolved processing,
storage problems, and captures that may deserve knowledge extraction.

These sections are contextual, dismissible, and evidence-fingerprinted. An
unchanged dismissed finding stays quiet until its evidence changes. Reviews never
become mandatory meal or exercise questionnaires.

Experiments can link a capture as an observation or supporting evidence. An
estimated meal value or inferred exercise value cannot become an experiment
measurement until you explicitly map and confirm it. The source capture remains
visible, and changed evidence becomes stale.

## From capture to action

Reviewed capture evidence can create proposals for tasks, habits, goals, plans,
knowledge notes, note sections, flashcard candidates, research questions,
reminders, calendar entries, expense integration, or review insights.

The preview shows the exact target path, patch, source capture hash, attachments,
confirmed and inferred fields, included actions, excluded actions, and stale-target
checks. Creating a proposal never applies it automatically.

## Timeline, gallery, and visualizations

Derived views can show a chronological timeline, gallery, meal and exercise lists,
activity calendar, capture-type and processing counts, workout duration or distance
trends, experiment links, and missing-data indicators. Every point retains the
canonical capture path. Raw records remain one action away.

Visualizations are bounded for large vaults. Unknown values are omitted and
reported as missing instead of plotted as zero. A rendering failure does not block
list view or canonical Markdown.

## Mobile and offline behavior

On mobile-sized screens, quick capture uses one column, large touch targets, and
delayed enrichment. Camera-originated files, clipboard content, mobile-share or
URI entry points, and offline capture are supported where the host platform
permits them. The original is saved before optional processing, so interrupted
capture or connectivity does not depend on a model response.

## Accessibility and keyboard controls

Controls have visible labels, logical focus order, non-color-only states, and
screen-reader status announcements. Attachment state is described in text rather
than only by a preview. Long operations expose progress, cancellation, and a
recovery action. Reduced-motion behavior does not remove information.

Use Tab and Shift+Tab to move among controls, Enter or Space to activate the
focused control, and Escape to close transient dialogs. Workspace shortcuts are
shown with descriptive accessible labels. Focus returns to the control that
opened a dialog.

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

The original capture and attachment remain intact. Open the canonical record,
audit attachment integrity, retry optional processing, or rebuild derived state.

## Migration, rebuilding, and recovery

No repository-defined legacy rich-capture format existed when Direction 7 was
introduced, so the current migration preview is an audited no-op. LifeOS does not
invent a legacy format. Future migrations must preserve source files, source
hashes, timestamps, links, and human annotations and must fail closed when sources
change.

You can delete `.lifeos/captures/` and rebuild indexes, manifests where enough
canonical evidence exists, extraction state, galleries, timelines, and other
derived views. Rebuilds are bounded, checkpointed, resumable, and report moved or
renamed captures, missing or changed originals, duplicate identities, stale
extraction, orphan files, and unsupported schema versions. Human-owned Markdown
is not rewritten merely to refresh a view.

[← Personal Experiments](12-personal-experiments.md) · [Manual home](README.md)
