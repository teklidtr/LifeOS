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

## 4.5 Create a vault with `lifeos init`

Choose a vault location **outside the LifeOS application repository**. The application
contains code; the vault contains your canonical configuration and personal Markdown.
Create the vault with the first-party bootstrap command:

```bash
lifeos init ~/LifeOS-vault
cd ~/LifeOS-vault
```

You can also initialize the current directory when it is empty:

```bash
lifeos init
```

`lifeos init` owns the canonical bootstrap contract. It creates the supported top-level
LifeOS roots, the vault configuration and bootstrap files, and initializes a local Git
repository. It does not configure Codex, Claude, Obsidian, or another external client.

Initialization is deliberately non-destructive:

- a missing or empty target is initialized;
- an existing recognized LifeOS vault returns successfully without rewriting user files;
- a non-empty unrecognized or partially initialized target fails without repairing or
  overwriting it;
- there is no destructive `--force` mode.

This means you may customize `system/instructions.yml`, `AGENTS.md`, and other canonical
content after initialization. Re-running `lifeos init` on that valid vault will not restore
template text over your changes.

## 4.6 What the bootstrap creates

The application owns the generated scaffold, so the manual does not duplicate its file
contents. The current bootstrap creates these top-level semantic roots:

`journal/`, `raw/`, `study/`, `wiki/`, `flashcards/`, `patterns/`, `profile/`, `goals/`,
`plans/`, `experiments/`, `metrics/`, `reviews/`, `proposals/`, and `system/`.

These roots provide LifeOS domain context. They do **not** define a universal ontology or
fixed subfolder structure. In particular, LifeOS does not prescribe an entity/concept/source
hierarchy under `wiki/`; an agent may evolve useful nested knowledge structure when needed.

The bootstrap also creates:

- `lifeos.yml`, whose portable defaults include `vault_root: .` and
  `runtime_dir: .lifeos`;
- a minimal vault-root `AGENTS.md` for clients that understand it;
- `system/instructions.yml` as the allowlisted source of vault-specific runtime
  instructions;
- `system/generated-ownership.json` for generated-file ownership metadata;
- `.gitignore` covering `.lifeos/` and disposable editor/OS state.

`.lifeos/` belongs to the vault but is disposable runtime state: registry, recovery,
activity diagnostics, graph/export generations, indexes, locks, and caches. `lifeos init`
does not need to populate it. Runtime commands create the state they need later. Do not
treat `.lifeos/` as canonical knowledge and do not commit it.

The vault `AGENTS.md` is a client convenience, not the cross-client source of truth. MCP
instructions remain the client-independent universal runtime contract, while
`system/instructions.yml` contains vault-specific or path-scoped guidance.

## 4.7 Vault configuration behavior

The generated vault-root `lifeos.yml` uses relative paths so the vault remains portable.
Relative `vault_root` values are resolved from the configuration file's directory, so
`vault_root: .` identifies the directory containing the file. Relative `runtime_dir` values
are resolved from the vault root, so `runtime_dir: .lifeos` keeps disposable state beside
the canonical vault without making it canonical.

The LifeOS executable may live anywhere; `--config` tells it which vault it is serving.
Configuration loading itself remains read-only.

Configuration rules:

- `vault_root` must already exist and be a directory;
- `runtime_dir` may be absent, but if present it must be a directory;
- unknown keys are rejected;
- `~` and environment variables are not expanded inside YAML;
- configuration loading does not create directories.

## 4.8 Initialize or explicitly refresh the registry

From the vault root, with the **application repository's virtual environment activated**:

```bash
lifeos scan --config ./lifeos.yml
```

Or invoke the executable by absolute path without activating the environment:

```bash
/absolute/path/to/lifeos-application/.venv/bin/lifeos \
  scan --config /absolute/path/to/LifeOS-vault/lifeos.yml
```

This is the explicit maintenance surface for populating or rebuilding disposable file and
proposal indexes, and `--json` provides structured automation output. You may run it after
manual imports, edits, moves, or deletions when you want registry state refreshed
immediately. A separate scan is **not** required before normal MCP proposal-building
ingestion: those ingestion tools run the authoritative full registry refresh automatically
immediately before source verification.

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

## 4.10 Verify the installation with `lifeos doctor`

The first readiness check should be the read-only doctor command. It accepts an explicit
configuration path, so it can be run from the application repository, the vault, or another
working directory:

```bash
lifeos doctor --config /absolute/path/to/LifeOS-vault/lifeos.yml
```

For machine-readable output:

```bash
lifeos doctor \
  --config /absolute/path/to/LifeOS-vault/lifeos.yml \
  --json
```

Doctor checks the installed LifeOS version, Python support, Git availability, configuration,
the current first-party vault bootstrap shape, and the existing read-only vault health
reported by `lifeos status`. It also reports whether the optional MCP SDK and `lifeos-mcp`
console script are available.

Doctor is diagnostic, not repair. It does **not** initialize or refresh the registry, create
runtime indexes, rebuild graph/export output, install packages, edit canonical Markdown, or
change Codex, Claude, Obsidian, shell, or another external client's configuration. This makes
it safe to run before `.lifeos/` exists.

Exit behavior is deliberately about blocking readiness rather than cosmetic completeness:

- exit `0` means no blocking environment, bootstrap, or vault-health condition was found;
- warnings such as optional MCP absence remain non-blocking;
- a fresh vault can be ready while disposable registry, graph, or export state is still
  missing or degraded;
- a blocking environment/bootstrap failure or an existing `status` condition classified as
  blocked produces a non-zero exit.

`lifeos status` remains the detailed vault subsystem view. After the first scan, run it from
the vault root:

```bash
lifeos status
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

Run doctor again after installing the extra:

```bash
lifeos doctor --config /absolute/path/to/LifeOS-vault/lifeos.yml
```

When `lifeos-mcp` is available, doctor prints a vault-scoped server command template ending
in `--actor-id <actor-id>`. The placeholder is intentional because trusted actor identity is
client-specific. Doctor never registers that command for you.

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

For durable knowledge, the preferred loop is read the source -> `vault_context` when
situational context matters -> `wiki_search` -> read relevant wiki hits -> decide. If no
durable knowledge changes, create no proposal. Otherwise use
`ingestion_evolve_wiki_proposal` with 1..12 distinct reviewed wiki creates/section updates.
The proposal-building ingestion call automatically refreshes the disposable registry before
source verification, so a separate `registry_refresh` call is unnecessary even when the
source was just created or edited.

For a registered source under `study/`, `study_evolve_learning_proposal` may combine those
wiki changes with selective flashcard creates in the **same atomic draft**. The same
automatic registry preflight runs before source verification. The external agent chooses
what merits retrieval practice according to the inferred learning context. Examples include
exam relevance, future prerequisites, conceptual leverage, mechanisms, and confusable
distinctions. LifeOS validates the reviewed paths, hashes, ownership, provenance, and
operation bounds; deterministic code does not decide which facts are educationally
important. Non-study sources do not get automatic flashcards by default.

Every proposal-producing ingestion tool still stops at draft. `proposal_submit`,
`proposal_approve`, and `proposal_apply` require separate explicit lifecycle intent.

For debugging, `runtime_activity` exposes recent disposable routing metadata such as tool
names, focus/source paths, applied instruction IDs, proposal IDs, targets, and changed paths.
Automatic ingestion refreshes appear as `ingestion_registry_preflight` activity records. It
does **not** copy canonical Markdown bodies or flashcard answers into `.lifeos` activity
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

`lifeos init` already initializes the vault's Git repository. After reviewing the generated
bootstrap and making any desired vault-specific instruction changes, create the first
canonical commit:

```bash
git add .gitignore AGENTS.md lifeos.yml system/generated-ownership.json system/instructions.yml
git commit -m "chore(vault): initialize LifeOS vault"
```

You now have a minimal, recoverable canonical foundation.

---

[← Previous: Feature Breakdown](03-feature-breakdown.md) · [Manual home](README.md) · [Next: Workflow →](05-workflow.md)
