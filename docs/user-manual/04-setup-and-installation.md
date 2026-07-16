[← Previous: Feature Breakdown](03-feature-breakdown.md) · [Manual home](README.md) · [Next: Workflow →](05-workflow.md)

# 4. Setup & Installation Guide

LifeOS is a local Python application and Markdown vault, not a hosted web
service. The core system requires no external account. AI ingestion and MCP
integration are optional.

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

- An AI provider account and API key for `lifeos ingest`
- An MCP-compatible agent client
- Graph and export features enabled in configuration

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

Install the core package:

```bash
uv sync
```

Install all optional features and development tools:

```bash
uv sync --all-extras
```

Or install only what you need:

```bash
uv sync --extra dev
uv sync --extra ai
uv sync --extra mcp
```

Verify the command:

```bash
uv run lifeos --version
uv run lifeos --help
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

The registry is explicit and disposable. From the LifeOS repository root, run:

```bash
uv run python - <<'PY'
from pathlib import Path

from lifeos.config import load_config
from lifeos.registry import Registry, register_proposals_scan, register_scan
from lifeos.scanner import scan_vault

config = load_config(Path("lifeos.yml"))
registry = Registry(config.runtime_dir / "registry.db")
registry.initialize()
register_scan(registry, config.vault_root, scan_vault(config.vault_root))
register_proposals_scan(registry, vault_root=config.vault_root)

print(f"Initialized and indexed {registry.database_path}")
PY
```

Run the same indexing snippet again after large manual imports or when you
intentionally rebuild the disposable registry.

## 4.9 Open the vault in Obsidian

1. Open Obsidian.
2. **Click “Open folder as vault.”**
3. Select `~/LifeOS-vault`.
4. Optionally enable **Daily Notes**, **Templates**, **Backlinks**, and
   **Properties view**.

No proprietary LifeOS Obsidian plugin is required for the core workflow. The first-class review workspace and other desktop cockpit views require the bundled LifeOS plugin, while the canonical Markdown artifacts remain usable without it.

## 4.10 Verify the installation

From the LifeOS application repository, where `lifeos.yml` exists:

```bash
uv run lifeos status
```

For machine-readable output:

```bash
uv run lifeos status --json
```

A fresh installation may report missing graph or export generations. That is
normal until you build them. A blocked recovery transaction or corrupt canonical
state should be investigated before consequential operations.

## 4.11 Optional AI setup

Install AI support:

```bash
uv sync --extra ai
```

Set the provider credential required by your model, for example:

```bash
export OPENAI_API_KEY="..."
export LIFEOS_AI_MODEL="openai:gpt-4o"
```

Before ingestion, make sure the source file has been registered. Then run:

```bash
uv run lifeos ingest \
  study/example.md \
  --target wiki/example.md
```

The result should be a draft proposal, not a direct wiki mutation.

## 4.12 Optional MCP setup

Install MCP support:

```bash
uv sync --extra mcp
```

Configure your MCP client to launch:

```bash
uv run lifeos-mcp \
  --config /absolute/path/to/lifeos.yml \
  --actor-id "your-trusted-identity"
```

Keep the server local and use STDIO transport. Do not expose it as an
unauthenticated network service.

## 4.13 Create the first vault commit

From the vault:

```bash
git add .gitignore system/generated-ownership.json
git commit -m "chore(vault): initialize LifeOS vault"
```

You now have a minimal, recoverable canonical foundation.

---

[← Previous: Feature Breakdown](03-feature-breakdown.md) · [Manual home](README.md) · [Next: Workflow →](05-workflow.md)
