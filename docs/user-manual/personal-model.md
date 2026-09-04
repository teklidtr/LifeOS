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

## Agent-assisted pattern proposals

An MCP-connected agent can help formulate a new working hypothesis or review an existing one, but it receives no special authority over the Personal Model. Agent assistance is an **evidence-bounded proposal aid**, not automatic profiling.

The agent first selects and reads the canonical evidence relevant to the question. Every evidence reference supplied to the proposal carries the exact vault path and SHA-256 content hash the agent actually inspected, plus its role as `supporting`, `contesting`, or `contextual`. For an existing pattern review, the agent must also bind the request to the exact canonical pattern hash it inspected.

LifeOS independently checks retrieval policy and rereads the selected sources before creating a draft. It verifies the evidence hashes again at the publication boundary. If a source is missing, changed, unsafe, protected without the required explicit grant and external allowlist, or otherwise unavailable, no draft is published. A changed existing pattern is likewise rejected rather than silently rebased.

The reviewable proposal keeps the agent's concise hypothesis, rationale, supporting and contesting evidence, competing explanations, limitations, and proposed qualitative confidence class visible. Counter-evidence stays inspectable instead of being averaged away. Hidden chain-of-thought is not stored, and these review fields do not become provider-specific canonical pattern fields.

The two MCP operations are:

- `personal_pattern_propose` for a new `seed` hypothesis;
- `personal_pattern_review_proposal` for a revision of an existing canonical pattern.

Both stop at a **draft proposal**. They cannot approve, apply, diagnose, promote a hypothesis to `active`, select the approving identity, or directly edit `patterns/`. If an existing pattern already has the same statement, confidence, and exact reviewed evidence set, `personal_pattern_review_proposal` returns `no-change` and creates nothing.

A model provider is optional. LifeOS can deterministically validate evidence and persist an externally supplied typed semantic candidate without a local model. When a provider is used, the contract is provider-neutral; timeout, provider failure, malformed output, or a provider returning no proposal creates no durable semantic authority.

On an authenticated home node, the same draft-producing tools are available through the shared MCP core, but remote clients still do not receive `proposal_approve` or `proposal_apply`. A remote agent can therefore help prepare something for review, not accept it on your behalf.

## Refresh versus rebuild

**Refresh** is read-only. It recomputes the presentation from canonical patterns and current authorized evidence without mutating pattern Markdown or rebuilding runtime files.

The Personal Model under `.lifeos/personal-model/` and the registry are disposable runtime state. If the derived generation is missing or unsafe to read, the workspace shows an explicit rebuild/recovery state. Choose **Rebuild derived state** to recreate it from canonical `patterns/*.md` and authorized evidence. Missing runtime state is not canonical data loss.

A malformed canonical pattern or inaccessible evidence is surfaced as a diagnostic or blocked state rather than guessed around. Protected and excluded paths continue to obey the local retrieval policy.

## What the workspace never does

The standard workspace does not maintain a personality dashboard, generate life/productivity scores, promote patterns automatically on startup, treat counter-evidence as an automatic truth decision, or write canonical pattern Markdown directly from TypeScript. Python remains the business-rule engine, and trusted proposal acceptance remains the boundary for durable semantic change.

[← Obsidian Desktop Cockpit](06-obsidian-desktop.md) · [Manual home](README.md)
