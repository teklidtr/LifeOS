[← Previous: Feature Breakdown](03-feature-breakdown.md) · [Manual home](README.md) · [Next: Workflow →](05-workflow.md)

# 4. Setup & Installation Guide

LifeOS is a local Python application and Markdown vault, not a hosted web
service. The core system requires no external account. Agent-assisted ingestion
uses an optional local MCP integration; LifeOS itself has no embedded model
client or provider API-key configuration.

## 4.1 Prerequisites

### Required

- Python **3.11 or newer**
- Git
- A local filesystem
- The LifeOS repository

### Recommended

- `uv` for Python environment management
- Obsidian for editing the Markdown vault
- macOS or Linux for the complete POSIX locking and descriptor-safety model
- Git version control around the vault

### Optional

- An MCP-compatible agent client for agent-assisted ingestion
- Graph and export features enabled in configuration
- A compatible local `pypdf` installation for PDF text extraction

## 4.2 Clone the repository

```bash
git clone <your-lifeos-repository-url> lifeos
cd lifeos
```

## 4.3 Install `uv`

On macOS with Homebrew:

```bash
brew install uv
```

Verify:

```bash
uv --version
```

## 4.4 Install LifeOS

Install the core package into the repository virtual environment and activate it:

```bash
uv sync
source .venv/bin/activate
```

`uv sync` installs the local LifeOS repository in editable mode, so source
changes are reflected without reinstalling it. Activate this environment in
each new shell before running LifeOS commands. From another directory, use the
absolute activation path, such as
`source /absolute/path/to/lifeos/.venv/bin/activate`.

Install all optional features and development tools:

```bash
uv sync --all-extras
```

Or install only what you need:

```bash
uv sync --extra dev
uv sync --extra mcp
```

Rich capture itself needs only the core installation. The repository currently
does not declare `pypdf` in `pyproject.toml` or `uv.lock`. PDF files are still
preserved without it, but local text extraction reports `unavailable`. Add and
lock a compatible parser in the same environment before relying on PDF
extraction. OCR, transcription, and model-based image or nutrition analysis are
not installed by any current extra.

Verify the command:

```bash
lifeos --version
lifeos --help
```

## 4.5 Create a vault

Choose a vault location **outside the LifeOS application repository**. The application
contains code; the vault contains your canonical configuration and personal Markdown.
Until LIFEOS-1634 adds guided Cookiecutter bootstrap, create the minimal skeleton manually:

```bash
mkdir -p ~/LifeOS-vault
cd ~/LifeOS-vault
mkdir -p \
  journal \
  raw \
  study \
  wiki \
  flashcards \
  patterns \
  profile \
  goals \
  plans \
  experiments \
  metrics \
  reviews \
  proposals \
  system
```

Initialize Git:

```bash
git init
```

Create `.gitignore`:

```gitignore
.lifeos/
.obsidian/workspace*.json
.DS_Store
```

`.lifeos/` belongs to this vault but is disposable runtime state: registry, recovery,
activity diagnostics, graph/export generations, indexes, locks, and caches. Do not treat
it as canonical knowledge and do not commit it.

## 4.6 Create canonical vault bootstrap files

Create `system/generated-ownership.json`:

```json
{
  "owned_files": {},
  "schema_version": 1
}
```

Create `system/instructions.yml` even when you do not have custom instructions yet:

```yaml
schema_version: 1
instructions: []
```

This file is the allowlisted source for **vault-specific** runtime instructions. Universal
LifeOS behavior comes from the MCP server itself. Later you can add scoped instructions,
for example exam-oriented study guidance, without turning folder names into permissions.

Create a minimal vault-root `AGENTS.md` for clients such as Codex that understand it:

```markdown
# LifeOS Vault Agent Bootstrap

This directory is a LifeOS vault, not the LifeOS application source repository.

Use the configured LifeOS MCP server for canonical search, context, proposals, and
consequential mutations. Obtain universal runtime policy from the MCP server and
vault-specific instructions through LifeOS. Folder names provide semantic context; do not
infer permission or a universal ontology from them. Do not directly rewrite canonical
LifeOS artifacts when an MCP/proposal workflow exists.
```

The vault `AGENTS.md` is a client convenience, not the cross-client source of truth. MCP
instructions remain the client-independent runtime contract.

## 4.7 Create vault-root `lifeos.yml`

Create `~/LifeOS-vault/lifeos.yml` **inside the vault root**:

```yaml
vault_root: .
runtime_dir: .lifeos
features:
  graphify: true
  exports: true
```

Relative `vault_root` values are resolved from the configuration file's directory, so
`vault_root: .` makes the vault portable. Relative `runtime_dir` values are resolved from
the vault root. The LifeOS executable may live anywhere; `--config` tells it which vault it
is serving.

Configuration rules:

- `vault_root` must already exist and be a directory;
- `runtime_dir` may be absent, but if present it must be a directory;
- unknown keys are rejected;
- `~` and environment variables are not expanded inside YAML;
- configuration loading is read-only and does not create directories.

## 4.8 Initialize and populate the registry

From the vault root, with the **application repository's virtual environment activated**:

```bash
lifeos scan --config ./lifeos.yml
```

Or invoke the executable by absolute path without activating the environment:

```bash
/absolute/path/to/lifeos-application/.venv/bin/lifeos \
  scan --config /absolute/path/to/LifeOS-vault/lifeos.yml
```

Run the same scan after manual imports, edits, moves, or deletions, or when intentionally
rebuilding the disposable registry. Use `--json` for structured automation output.

## 4.9 Open the vault in Obsidian

1. Open Obsidian.
2. **Click “Open folder as vault.”**
3. Select `~/LifeOS-vault`.
4. Optionally enable **Daily Notes**, **Templates**, **Backlinks**, and **Properties view**.

No proprietary LifeOS Obsidian plugin is required for the core workflow. The first-class
review workspace and other desktop cockpit views require the bundled LifeOS plugin, while
the canonical Markdown artifacts remain usable without it.

To build and install the optional bundled plugin, follow
[Obsidian Desktop Cockpit → First run](06-obsidian-desktop.md#first-run). Build it from the
LifeOS application repository; install only the resulting `main.js`, `manifest.json`, and
`styles.css` in the vault's `.obsidian/plugins/lifeos/` directory.

## 4.10 Verify the installation

From the vault root:

```bash
lifeos status
```

For machine-readable output:

```bash
lifeos status --json
```

A fresh installation may report missing graph or export generations. That is normal until
you build them. A blocked recovery transaction or corrupt canonical state should be
investigated before consequential operations.

You can also verify context routing without changing canonical files:

```bash
lifeos context build "What context is relevant?" --json
```

When you already know the source being worked on, use repeatable `--focus-path` so path- or
domain-scoped instructions apply even if lexical retrieval would not select the source:

```bash
lifeos context build "What should I prioritize while studying this?" \
  --focus-path study/example/topic.md \
  --json
```

## 4.11 Optional MCP setup

Install MCP support in the **application repository**:

```bash
cd /absolute/path/to/lifeos-application
uv sync --extra mcp
```

The server executable lives with the application; the configuration lives with the vault:

```text
lifeos application/.venv/bin/lifeos-mcp
                     │
                     └── --config → LifeOS-vault/lifeos.yml
                                         │
                                         └── vault_root: .
```

For Codex, register the local STDIO server explicitly. Using the absolute executable path
avoids depending on shell activation or `PATH`:

```bash
codex mcp add lifeos -- \
  /absolute/path/to/lifeos-application/.venv/bin/lifeos-mcp \
  --config /absolute/path/to/LifeOS-vault/lifeos.yml \
  --actor-id your-codex-identity
```

Verify the Codex registration:

```bash
codex mcp list
```

For another MCP-compatible client, configure the same executable and arguments directly:

```bash
/absolute/path/to/lifeos-application/.venv/bin/lifeos-mcp \
  --config /absolute/path/to/LifeOS-vault/lifeos.yml \
  --actor-id your-trusted-identity
```

Keep the server local and use STDIO transport. Do not expose it as an unauthenticated
network service.

The MCP server supplies universal LifeOS runtime instructions. `system/instructions.yml`
supplies this vault's scoped behavioral instructions. The application repository's
`AGENTS.md` is for developing LifeOS and is not inherited merely because an MCP server is
being used.

For reasoning where personal context can change the answer, the agent should call
`vault_context` with explicit focus paths. The result may include applicable instructions
plus relevant canonical study, goals, journal, experiments, plans, wiki, or other Markdown.
Folder location is context, not an allowlist: any registered canonical Markdown source may
ground durable wiki evolution when relevant.

For durable knowledge, the preferred loop is `registry_refresh` as needed -> read the source
-> `vault_context` when situational context matters -> `wiki_search` -> read relevant wiki
hits -> decide. If no durable knowledge changes, create no proposal. Otherwise use
`ingestion_evolve_wiki_proposal` with 1..12 distinct reviewed wiki creates/section updates.

For a registered source under `study/`, `study_evolve_learning_proposal` may combine those
wiki changes with selective flashcard creates in the **same atomic draft**. The external
agent chooses what merits retrieval practice according to the inferred learning context.
Examples include exam relevance, future prerequisites, conceptual leverage, mechanisms, and
confusable distinctions. LifeOS validates the reviewed paths, hashes, ownership, provenance,
and operation bounds; deterministic code does not decide which facts are educationally
important. Non-study sources do not get automatic flashcards by default.

Every proposal-producing ingestion tool still stops at draft. `proposal_submit`,
`proposal_approve`, and `proposal_apply` require separate explicit lifecycle intent.

For debugging, `runtime_activity` exposes recent disposable routing metadata such as tool
names, focus/source paths, applied instruction IDs, proposal IDs, targets, and changed paths.
It does **not** copy canonical Markdown bodies or flashcard answers into `.lifeos` activity
logs.

## 4.12 Build the semantic retrieval index

After enabling the desktop plugin, open **Knowledge Conversation** and choose
**Rebuild index**. The first build scans allowed Markdown, creates structural
chunks, and publishes `.lifeos/retrieval/index.sqlite3` only when complete.
Embeddings are optional. Without an embedding adapter, exact, lexical, metadata,
link, and graph retrieval remain available.

Review the protected and excluded prefixes before enabling an external adapter.
The workspace discloses the exact selected passages before external generation.
Provider configuration remains runtime-specific and is not written into canonical
conversation fields.


## 4.13 Create the first vault commit

From the vault:

```bash
git add .gitignore AGENTS.md lifeos.yml system/generated-ownership.json system/instructions.yml
git commit -m "chore(vault): initialize LifeOS vault"
```

You now have a minimal, recoverable canonical foundation.

---

[← Previous: Feature Breakdown](03-feature-breakdown.md) · [Manual home](README.md) · [Next: Workflow →](05-workflow.md)
