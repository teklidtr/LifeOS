[← Previous: Rich Capture](13-rich-capture.md) · [Manual home](README.md)

# 14. Generated Wiki Source History

LifeOS-generated Wiki pages remember the canonical sources that contributed to them over time.

The simplest way to think about this is **References in an academic paper**. A generated Wiki page is an evolving synthesis, and its provenance is the source history behind that synthesis.

## 14.1 What problem this solves

Suppose LifeOS first creates `wiki/creatine.md` from:

```text
notes/creatine.md
```

Later, a journal note adds useful information:

```text
journal/2026-08-23.md
```

Without cumulative source history, the Wiki page could remember only the first source or only the most recent one. You would lose the answer to a basic question: **which canonical notes have actually contributed to this page?**

With cumulative provenance, the generated Wiki page keeps both references.

## 14.2 What you will see in the page

Generated pages carry a `lifeos_provenance` block in YAML frontmatter. A simplified example looks like this:

```yaml
lifeos_provenance:
  schema_version: 1
  sources:
    - path: notes/creatine.md
      content_hash: sha256:1111111111111111111111111111111111111111111111111111111111111111
    - path: journal/2026-08-23.md
      content_hash: sha256:2222222222222222222222222222222222222222222222222222222222222222
```

The paths tell you which canonical files contributed. The hashes identify the exact source snapshots that were used at the time.

You normally do not need to edit this block manually. It is machine-maintained evidence lineage that stays visible in ordinary Markdown.

## 14.3 What happens when the same source is used again

LifeOS does not add an identical reference twice.

If `notes/creatine.md` contributes again without changing, the same `(path, content_hash)` pair is already present and is not duplicated.

If that file changes and the newer version later contributes to the generated Wiki page, LifeOS keeps both snapshots. For example:

```yaml
sources:
  - path: notes/creatine.md
    content_hash: sha256:1111111111111111111111111111111111111111111111111111111111111111
  - path: notes/creatine.md
    content_hash: sha256:3333333333333333333333333333333333333333333333333333333333333333
```

That is intentional. It means the page can retain the history that an earlier version of the note contributed first and a later version contributed afterward.

## 14.4 Source history is not write permission

This distinction matters:

- **Provenance / source history:** where the generated knowledge came from.
- **Generated ownership:** whether LifeOS is authorized to replace the generated file automatically through its generated-file workflow.

A file does not become LifeOS-owned merely because it appears in provenance, and a provenance block does not grant write authority.

Human-owned Wiki pages remain human-owned. If an ingestion proposal updates one exact section of a human-owned page, LifeOS does not attach generated provenance to the page just because the source participated in that proposal.

## 14.5 Current proposal versus lifetime references

The proposal you are reviewing may be grounded in only one current source, while the resulting generated page can retain many historical sources.

For example:

```text
Current proposal source:
  journal/2026-08-23.md

Generated page references after acceptance:
  notes/creatine.md
  journal/2026-08-23.md
  papers/creatine-review.md
```

That difference is expected. Proposal metadata explains **this change**; page provenance explains **the generated page's accumulated lineage**.

## 14.6 Several files can contribute in one batch

Folder ingestion can review several source files together and still create only one change for a
generated Wiki target. If `notes/a.md` and `notes/b.md` both support the reconciled update to
`wiki/topic.md`, that one reviewed replacement adds both verified source snapshots to the page's
history in the same operation.

A third file selected elsewhere in the folder does **not** appear in `wiki/topic.md` provenance
unless it actually grounds that target. The proposal shows a target-to-source grounding map so
you can distinguish “selected for this batch” from “contributed to this page.” Existing accepted
history remains first, new relevant snapshots are appended deterministically, and exact repeats
are not duplicated.

This is why folder ingestion is not implemented as one proposal per source file. The proposal is
reconciled by target first, so a page receives one reviewed candidate and one coherent provenance
update rather than several sibling drafts that immediately make one another stale.

## 14.7 Why `sources` contains objects instead of only paths

The current schema keeps each source as an object:

```yaml
sources:
  - path: notes/creatine.md
    content_hash: sha256:...
```

rather than storing only a list of paths. This is slightly more verbose, but it lets LifeOS attach source-specific metadata later without redesigning the entire provenance format.

The schema remains `schema_version: 1`; there is no version-2 migration for this behavior.

## 14.8 What provenance does not mean

A source appearing in the list does not mean every sentence in the Wiki page came from that source. The current contract records **page-level contribution history**, not claim-by-claim citations.

A future citation layer could become more granular, but the present goal is simpler and useful on its own: a generated Wiki page should not forget the canonical sources that helped it evolve.

For the exact technical contract, see [Generated Wiki Provenance](../generated-wiki-provenance.md).

---

[← Previous: Rich Capture](13-rich-capture.md) · [Manual home](README.md)
