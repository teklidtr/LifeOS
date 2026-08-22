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

Choose a location outside the application repository or create a dedicated vault
folder inside a private workspace:

```bash
mkdir -p ~/LifeOS-vault
cd ~/LifeOS-vault
```

Create the main domains:

```bash
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

The `.lifeos/` directory contains disposable registry, recovery, graph, export,
and cache state. Do not treat it as canonical knowledge.

## 4.6 Create the ownership manifest

Create `system/generated-ownership.json`:

```json
{
  "owned_files": {},
  "schema_version": 1
}
```

Commit this file with the vault. It is durable authorization state, not runtime
cache.

## 4.7 Create `lifeos.yml`

LifeOS CLI commands currently load `lifeos.yml` from the current working
directory. A convenient arrangement is to keep the configuration in the
application repository while pointing it to your separate vault.

From the LifeOS repository root, create:

```yaml
vault_root: /Users/you/LifeOS-vault
runtime_dir: .lifeos
features:
  graphify: true
  exports: true
```

You may use a relative vault path. Relative `vault_root` values are resolved
from the configuration file's directory. Relative `runtime_dir` values are
resolved from the vault root.

Configuration rules:

- `vault_root` must already exist and be a directory;
- `runtime_dir` may be absent, but if present it must be a directory;
- unknown keys are rejected;
- `~` and environment variables are not expanded inside YAML;
- configuration loading is read-only and does not create directories.

## 4.8 Initialize and populate the registry

The registry is explicit and disposable. With the LifeOS repository virtual
environment activated, run:

```bash
uv run lifeos scan --config /absolute/path/to/LifeOS-vault/lifeos.yml
```

Run the same command after manual imports, edits, moves, or deletions, or when
you intentionally rebuild the disposable registry. Use `--json` for structured
automation output.

## 4.9 Open the vault in Obsidian

1. Open Obsidian.
2. **Click “Open folder as vault.”**
3. Select `~/LifeOS-vault`.
4. Optionally enable **Daily Notes**, **Templates**, **Backlinks**, and
   **Properties view**.

No proprietary LifeOS Obsidian plugin is required for the core workflow. The first-class review workspace and other desktop cockpit views require the bundled LifeOS plugin, while the canonical Markdown artifacts remain usable without it.

To build and install the optional bundled plugin, follow
[Obsidian Desktop Cockpit → First run](06-obsidian-desktop.md#first-run). Build it
from the LifeOS application repository; install only the resulting `main.js`,
`manifest.json`, and `styles.css` in the vault's `.obsidian/plugins/lifeos/`
directory.

## 4.10 Verify the installation

From the directory containing `lifeos.yml`, with the LifeOS repository virtual
environment activated:

```bash
lifeos status
```

For machine-readable output:

```bash
lifeos status --json
```

A fresh installation may report missing graph or export generations. That is
normal until you build them. A blocked recovery transaction or corrupt canonical
state should be investigated before consequential operations.

## 4.11 Optional MCP setup

Install MCP support:

```bash
uv sync --extra mcp
```

Configure your MCP client to launch:

```bash
lifeos-mcp \
  --config /absolute/path/to/lifeos.yml \
  --actor-id "your-trusted-identity"
```

Keep the server local and use STDIO transport. Do not expose it as an
unauthenticated network service.

After the MCP client connects, an ingestion request such as “Ingest
`study/example.md` into `wiki/example.md` using LifeOS” is routed through
`registry_refresh`, `vault_read_markdown`, and
`ingestion_create_wiki_proposal`. The default result is a draft proposal. The
server does not infer permission to submit, approve, or apply it.

If the explicit wiki target already exists, read it with `vault_read_markdown`
and use `ingestion_update_wiki_section_proposal` with one unique ATX heading and
its replacement body. Supply heading text without `#` markers. This produces a
base-hash-bound draft patch and preserves the rest of the note; it does not
perform a whole-note semantic merge.

This is the only supported agent-assisted ingestion route. The connected agent
supplies semantic interpretation; LifeOS does not accept a model name, provider
API key, or environment-based model configuration. The MCP workflow refreshes
the disposable registry so the source is registered with its current path and
hash before ingestion.

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
git add .gitignore system/generated-ownership.json
git commit -m "chore(vault): initialize LifeOS vault"
```

You now have a minimal, recoverable canonical foundation.

---

[← Previous: Feature Breakdown](03-feature-breakdown.md) · [Manual home](README.md) · [Next: Workflow →](05-workflow.md)
