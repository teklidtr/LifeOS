---
id: LIFEOS-1634
title: Add guided vault bootstrap with Cookiecutter
status: ready
phase: 16
depends_on:
  - LIFEOS-1633
risk: medium
---

# Goal

Replace error-prone manual vault bootstrap steps with a guided, reproducible template
workflow so a new user does not have to hand-create directories and canonical bootstrap
files.

# Scope

- Evaluate and adopt Cookiecutter as the vault-template engine.
- Provide one supported LifeOS bootstrap entry point that renders the canonical vault
  skeleton, `lifeos.yml`, minimal `AGENTS.md`, `system/instructions.yml`, ownership
  manifest, `.gitignore`, and required roots.
- Preserve the LIFEOS-1633 fresh-vault integration contract as the acceptance test for
  generated vaults.
- Simplify Setup & Installation Guide around the guided command.
- Keep MCP client registration explicit and testable.

# Out of scope

- Reworking runtime policy/context semantics established by LIFEOS-1633.
- Choosing or enforcing a universal wiki/study folder taxonomy.

# Acceptance criteria

- A fresh user can create a valid vault without manual `mkdir`/file-copy steps.
- Generated vaults pass the same setup/MCP integration contract as manually bootstrapped
  LIFEOS-1633 vaults.
- Re-running bootstrap fails safely or provides an explicit non-destructive mode.
- Documentation no longer duplicates template contents by hand.
