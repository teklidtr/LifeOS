# LifeOS

LifeOS is a private, local, Obsidian-native system for durable knowledge, study and
flashcards, adaptive planning, journals and metrics, personal observation, experiments,
rich capture, evidence-grounded conversations, and proposal-based agent assistance.

Its purpose is to help the user understand how they work, not merely maximize task
completion.

## Application repository vs vault

This repository contains the **LifeOS application**. Your personal Markdown belongs in a
separate **LifeOS vault**. The application supplies deterministic business rules, CLI tools,
the optional Obsidian plugin, and a local MCP server. The vault remains portable canonical
Markdown plus a small amount of Git-tracked system metadata.

Agent-assisted ingestion is MCP-only. LifeOS does not embed an ingestion model runtime or
require a provider API key. External agents connect to the local STDIO MCP server and can
produce reviewable proposals; they do not silently rewrite canonical notes.

## Quick start

Requirements: Python 3.11+, Git, and preferably `uv`.

Install the application:

```bash
uv sync
source .venv/bin/activate
```

Create a separate vault with the first-party bootstrap:

```bash
lifeos init ~/LifeOS-vault
cd ~/LifeOS-vault
lifeos scan --config ./lifeos.yml
lifeos status
```

`lifeos init` is non-destructive. It creates the supported canonical bootstrap roots and
files, initializes Git, and refuses to overwrite a conflicting or partial vault. Re-running
it on a recognized LifeOS vault does not restore template text over your edits.

For MCP-assisted workflows, install the optional MCP dependency in the application
repository and register `lifeos-mcp` with your client explicitly:

```bash
cd /absolute/path/to/lifeos-application
uv sync --extra mcp
```

See the Setup & Installation Guide for the tested Codex registration command, vault/runtime
boundaries, and Obsidian plugin installation.

## User documentation

- [Complete User Manual](docs/user-manual/README.md)
- [Setup & Installation](docs/user-manual/04-setup-and-installation.md)
- [Step-by-Step Workflow](docs/user-manual/05-workflow.md)
- [Obsidian Desktop Cockpit](docs/user-manual/06-obsidian-desktop.md)
- [Generated Wiki Source History / References](docs/user-manual/14-generated-wiki-source-history.md)
- [System architecture](docs/architecture.md)
- [Design decisions](docs/design-decisions.md)

## Development

When changing the LifeOS application itself:

1. Read `AGENTS.md`.
2. Read `docs/vision.md` and the relevant architecture/design documentation.
3. Select exactly one task from `tasks/ready/`.
4. Follow the task lifecycle and documentation-impact rules in `tasks/README.md`.

Small verifiable tasks evolve the application; completed task files are implementation
history, not a substitute for current user or architecture documentation.
