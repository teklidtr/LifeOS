# Historical Documentation Debt Audit — 2026-08-23

## Purpose

This audit reconciles current LifeOS documentation with behavior that is already implemented.
Completed task files were used to identify likely areas of drift, but code and tests were treated
as the source of truth for current behavior.

The audit prioritizes the surfaces named by LIFEOS-1636: setup/init, MCP, ingestion and Wiki
evolution, proposals, generated ownership, provenance, registry, and user-visible operating
workflows.

## Evidence checked

The audit compared the current documentation against:

- `src/lifeos/bootstrap.py` and the `lifeos init` CLI/integration tests;
- `src/lifeos/cli.py` and CLI tests;
- `src/lifeos/mcp/server.py` and MCP schema/server tests;
- `src/lifeos/facade/registry_tools.py` plus registry migration/provenance-index tests;
- ingestion proposal/facade tests, including agent-directed Wiki evolution;
- proposal desktop, immutable review snapshot, application, and recovery tests;
- generated-ownership reconciliation code/tests;
- the current generated-Wiki provenance parser, registry index, and LIFEOS-1628 tests.

Recent completed tasks reviewed as change-history pointers include LIFEOS-1613, LIFEOS-1624,
LIFEOS-1627, LIFEOS-1628, LIFEOS-1629, LIFEOS-1630, LIFEOS-1631, LIFEOS-1632, LIFEOS-1633,
LIFEOS-1633A, LIFEOS-1634, and LIFEOS-1635.

## Findings and corrections

| Area | Audit finding | Resolution |
| --- | --- | --- |
| MCP-only ingestion | Troubleshooting still recommended the older single-create, single-update, and fixed two-operation ingestion tools and initially suggested typed `page_kind + slug` routing. Current MCP policy prefers `wiki_search` plus `ingestion_evolve_wiki_proposal`, permits zero durable changes, and treats Wiki structure as emergent. | Updated troubleshooting to the current search/read/decide/evolve flow and kept old tools explicitly described as compatibility surfaces only. |
| Proposal acceptance | The daily workflow correctly described one **Accept changes** confirmation, but the weekly workflow still told users to click Submit, Approve, and Apply separately. | Updated the weekly workflow to the same composite **Accept changes** model while retaining the internal durable lifecycle explanation. |
| Registry location | `docs/registry.md` named `state.sqlite` as the conventional database, while the shipped CLI uses `<runtime_dir>/registry.db`. | Corrected the documented operational location to `registry.db`. |
| Registry refresh semantics | Documentation blurred the general registry schema with the supported `lifeos scan` / MCP `registry_refresh` operation. The shipped facade refreshes file and proposal indexes; provenance has a separate `refresh_provenance_index()` operation. | Documented the two refresh surfaces explicitly and stopped implying that `lifeos scan` refreshes provenance rows. |
| Registry scope | Architecture text implied the current SQLite registry stored ownership, task, and graph state. Current registry migrations actually cover file/source facts, generated outputs, proposal indexing, and provenance indexing; canonical ownership remains outside SQLite. | Narrowed the architecture description to the current implemented registry contract. |
| Canonical domain inventory | Architecture's example vault list omitted implemented canonical areas used by proposals, knowledge conversations, rich captures, and attachment evidence. | Expanded the architecture inventory and distinguished first-party bootstrap roots from feature-owned canonical areas. |
| First-party bootstrap | Setup already accurately documents `lifeos init`, but the repository README still read primarily as an implementation bootstrap/scaffold and did not offer the current first-party vault quick start. The durable non-destructive bootstrap policy also existed mainly in LIFEOS-1634 plus code. | Reframed README around the current product/application-vs-vault model, added the supported quick start, added the bootstrap boundary to architecture, and promoted the bootstrap contract into `docs/design-decisions.md`. |
| Generated ownership recovery | Current troubleshooting, desktop manual, safety/ownership docs, and tests agree that orphaned ownership is explicit restore-or-release work and never a registry-refresh side effect. | Verified; no rewrite needed. |
| Immutable proposal review history | Current workflow, desktop manual, architecture, and DD-083 agree on `review.json`, digest binding, and the legacy live-preview fallback. | Verified; no rewrite needed. |
| Cumulative generated-Wiki provenance | LIFEOS-1628 documentation, data model, registry indexing, and tests agree on schema version 1 with ordered source snapshots, exact snapshot deduplication, same-path/new-hash history, and ownership independence. | Verified; no rewrite needed. |
| Setup/MCP runtime policy | Setup matches the first-party bootstrap and current MCP policy: application and vault are separate, MCP is local STDIO, `system/instructions.yml` is the vault instruction authority, and client registration remains explicit. | Verified; no rewrite needed. |
| Documentation completion gate | AGENTS/task workflow and CI already contain the LIFEOS-1635 documentation-impact contract. This is a repository-development rule rather than a user runtime feature. | Verified in developer/process docs; no user-manual duplication added. |

## Durable decision promoted from task history

The first-party bootstrap contract from LIFEOS-1634 is durable enough to be a design decision:
LifeOS owns its vault bootstrap, initialization is deterministic and non-destructive, recognized
vault reruns do not rewrite user content, conflicting or partial targets fail closed, and client
configuration is not mutated implicitly. This is now recorded as DD-088.

## Documentation intentionally left unchanged

The audit did not rewrite documentation merely for style. In particular:

- `docs/user-manual/04-setup-and-installation.md` already matches `bootstrap.py`, configuration
  resolution, explicit MCP registration, and the tested fresh-vault flow;
- generated-Wiki provenance documentation already reflects LIFEOS-1628;
- generated-ownership recovery documentation already reflects LIFEOS-1627;
- the Obsidian proposal workspace already reflects composite acceptance and immutable review
  snapshots;
- DD-079 through DD-087 already capture the recent MCP, ownership, proposal-review, taxonomy,
  emergent-Wiki, and runtime-policy decisions.

## Follow-up scope

No documentation-structure defect discovered in this audit requires a separate backlog task.
Future product work remains subject to the LIFEOS-1635 documentation-impact gate so new drift
should be caught at task completion rather than accumulated for another historical sweep.
