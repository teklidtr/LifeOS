[← Obsidian Desktop Cockpit](06-obsidian-desktop.md) · [Manual home](README.md)

# Personal Model workspace

The **Personal Model** workspace is LifeOS's Obsidian-native place for inspecting evidence-backed working hypotheses about how you tend to work, learn, recover, choose, or respond to context. A pattern is not a personality fact, diagnosis, score, or instruction. Even an `active` pattern remains provisional and reviewable.

## Open the workspace

Use the **Open Personal Model** ribbon button or run **Open Personal Model** from the command palette. Normal review does not require the CLI or editing YAML.

The workspace has four lifecycle views:

- **Needs review** contains hypotheses whose evidence, timing, or explicit review state deserves attention.
- **Active** contains hypotheses you previously reviewed and currently accept as useful working context.
- **Seeds** contains exploratory hypotheses you chose to track without adopting them.
- **Archived** keeps history outside normal active context.

Use Left/Right Arrow, Home, and End while a lifecycle tab has focus to move between the four views. Pattern rows and all actions are native keyboard-focusable controls. Status changes are announced through the workspace live-status region.

## Inspect before deciding

Select a pattern to see its canonical statement, lifecycle status, confidence class, evidence health, freshness, review timing, and the reasons it deserves attention. Confidence is qualitative working context, not a probability or score.

The **Reviewed evidence** section keeps each reference's role and reviewed content hash visible. Use **Open source** to open the canonical source. When a source has moved, the workspace opens the uniquely resolved current path while still showing the path and hash that were actually reviewed.

The **Evidence changes since the reviewed version** section reports factual changes such as moved, changed, missing, deleted, or ambiguous evidence. These states are reasons to inspect the hypothesis. They do not automatically mean support or contradiction, and LifeOS never silently advances the stored reviewed hash.

Links to canonical reviews and experiments appear when they are part of the pattern origin or evidence. Use those links to inspect the surrounding reflection or experiment rather than treating the Personal Model card as a self-contained verdict.

## Track a seed

Expand **Track a new seed hypothesis**. Give the hypothesis a stable ID, canonical `patterns/*.md` path, title, cautious statement, confidence class, and a reason for tracking it.

**Track** creates a proposal preview first. It does not create the canonical pattern immediately. A seed means “this may be worth revisiting,” not “LifeOS has learned this about me.”

## Adopt, revise, contest, or archive

Consequential actions are always proposal-backed:

- **Adopt** proposes moving a reviewed seed or `needs-review` pattern into active working context.
- **Revise** proposes changing the statement and/or confidence after you inspect the visible evidence.
- **Contest** proposes moving a currently used hypothesis to `needs-review`; it does not declare the hypothesis false.
- **Archive** proposes removing a hypothesis from ordinary active context while preserving its history.

Enter the reason for the proposed change, then choose the action. Python builds the exact candidate Markdown and the workspace shows it under **Proposal preview**. At this point no canonical pattern has changed.

Choose **Create draft proposal** only after the candidate matches what you intended. The draft then appears in **Open Proposals**, where the normal LifeOS proposal review and acceptance workflow applies. Canceling the preview creates nothing.

The workspace binds actions to the exact pattern content hash you inspected. If the canonical pattern changes in Obsidian before preview or draft creation, the action stops with a stale-target state. Refresh, inspect the new pattern and evidence, and create a new preview. LifeOS does not silently attach your decision to the newer content.

## Refresh versus rebuild

**Refresh** is read-only. It recomputes the presentation from canonical patterns and current authorized evidence without mutating pattern Markdown or rebuilding runtime files.

The Personal Model under `.lifeos/personal-model/` and the registry are disposable runtime state. If the derived generation is missing or unsafe to read, the workspace shows an explicit rebuild/recovery state. Choose **Rebuild derived state** to recreate it from canonical `patterns/*.md` and authorized evidence. Missing runtime state is not canonical data loss.

A malformed canonical pattern or inaccessible evidence is surfaced as a diagnostic or blocked state rather than guessed around. Protected and excluded paths continue to obey the local retrieval policy.

## What the workspace never does

The standard workspace does not maintain a personality dashboard, generate life/productivity scores, promote patterns automatically on startup, treat counter-evidence as an automatic truth decision, or write canonical pattern Markdown directly from TypeScript. Python remains the business-rule engine, and trusted proposal acceptance remains the boundary for durable semantic change.

[← Obsidian Desktop Cockpit](06-obsidian-desktop.md) · [Manual home](README.md)
