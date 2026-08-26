[← Previous: Feature Breakdown](03-feature-breakdown.md) · [Manual home](README.md) · [Next: Workflow →](05-workflow.md)

# 4. Setup & Installation Guide

LifeOS is a local/private Python application and Markdown vault, not a managed hosted
service. The core system requires no external account. Agent-assisted ingestion uses optional
MCP integration over local STDIO or an explicitly configured authenticated home-node
transport; LifeOS itself has no embedded model client or provider API-key configuration.

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

For this local mode, keep the server on STDIO. Do not improvise an unauthenticated HTTP
wrapper around `lifeos-mcp`; use the supported authenticated `lifeos serve` home-node mode in
Section 4.15 when the MCP endpoint must be reachable over a network.

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

## 4.14 Cross-device placement and synchronization

The supported cross-device model is one human and **one active LifeOS mutation endpoint** for
a synchronized canonical vault view. Sync transports remain external to LifeOS. Supported
patterns include:

- one desktop vault with its local STDIO LifeOS process;
- one authoritative always-on LifeOS node while desktop/mobile Obsidian copies synchronize
  canonical files to it;
- one always-on LifeOS node operating directly on a mounted/shared canonical filesystem;
- offline mobile capture where the phone writes normal Markdown and LifeOS discovers it only
  after synchronization reaches the active node.

Do not run independent LifeOS mutation authorities against separate synchronized replicas at
the same time. LifeOS does not provide distributed locking, CRDTs, multi-master merge, or a
provider freshness oracle. The sync provider may copy Markdown and other canonical vault
artifacts, but `.lifeos/` registry/retrieval/cache state should stay node-local and rebuildable.
Likewise, the active LifeOS node owns Git commits for LifeOS proposal/application activity;
every phone or desktop replica does not need to commit independently.

If `runtime_dir` remains `.lifeos` inside the vault directory, configure the sync provider to
exclude it where possible. Also avoid syncing `.git/` as a live multi-client working state and
avoid treating Obsidian workspace files as canonical LifeOS state. `lifeos doctor` reports the
resolved writer model, runtime placement, and stable-ID diagnostics so an operator can inspect
this boundary before enabling an always-on node.

For notes that need rename/move continuity, preserve their frontmatter `id`. Durable wiki notes
are expected to have one. The ID answers **which note**, the current vault-relative path answers
**where**, and the SHA-256 content hash answers **which version**. Duplicate IDs are unsafe and
block identity resolution. A legacy note without an ID remains usable but a later rename cannot
be proven to be the same note automatically.

See [Cross-Device Vault Coherence](16-cross-device-vault-coherence.md) before configuring a
synchronized or mounted deployment.

## 4.15 Run an always-on home node

Use the home-node service when a phone, laptop, or tablet should reach one authoritative
LifeOS node without storing a local vault copy. The node owns the filesystem view and runs the
same deterministic MCP tool/facade surface as local STDIO; agent intelligence still runs in
the external client.

### Direct service mode

Install the MCP extra and check the selected vault first:

```bash
uv sync --extra mcp
lifeos doctor --config /absolute/path/to/LifeOS-vault/lifeos.yml
```

Create a high-entropy bearer secret outside the vault. A file is preferable for a long-lived
service because process launch configuration does not contain the secret value:

```bash
mkdir -p ~/.config/lifeos
python -c 'import secrets; print(secrets.token_urlsafe(48))' \
  > ~/.config/lifeos/home-node-token
chmod 600 ~/.config/lifeos/home-node-token
export LIFEOS_SERVICE_TOKEN_FILE="$HOME/.config/lifeos/home-node-token"
```

Set exactly one of `LIFEOS_SERVICE_TOKEN` or `LIFEOS_SERVICE_TOKEN_FILE`. The token must be at
least 32 characters. Do not place it in canonical Markdown, `lifeos.yml`, Git, or a vault
activity note.

Start the service locally:

```bash
lifeos serve \
  --config /absolute/path/to/LifeOS-vault/lifeos.yml \
  --actor-id home-node
```

The service fails before accepting MCP traffic unless its process identity can read/write the
canonical vault root and `proposals/`, and can use or create the configured runtime directory.
This is deliberate: a node that can only read the vault must not advertise a working remote
draft/submit surface.

The default bind is `127.0.0.1:8000`. The Streamable HTTP MCP endpoint is `/mcp`.
`/healthz` is a public, content-free liveness probe. `/readyz` runs the deterministic readiness
contract and returns 503 when the node is blocked, but it requires the same bearer credential as
`/mcp` because readiness can be influenced by protected canonical state. An unauthenticated
`/readyz` request returns 401. Neither probe returns the bearer secret or vault content.

A non-loopback bind is rejected unless you also supply at least one explicit Host allowlist:

```bash
lifeos serve \
  --config /absolute/path/to/LifeOS-vault/lifeos.yml \
  --actor-id home-node \
  --host 0.0.0.0 \
  --allowed-host 'lifeos.example.internal:*'
```

`--allowed-origin` configures the MCP SDK's Origin validation for transport security. It does
**not** add CORS response headers or make this service a direct cross-origin browser endpoint.
Use a non-browser MCP client, or place browser-specific integration behind an operator-owned
authenticated gateway/reverse proxy that owns the required CORS policy.

Treat network binding as only one layer of the boundary. Supported exposure patterns are a
trusted private LAN, a VPN/overlay network, or an authenticated TLS reverse proxy. For traffic
leaving a trusted host/network boundary, terminate TLS before forwarding to LifeOS. Do not
publish port 8000 directly to the public Internet. LifeOS does not configure routers, VPNs, DNS,
certificates, reverse proxies, or browser CORS for you.

The configured `--actor-id` is the stable attribution for authenticated requests handled by
that service process. The initial headless contract permits an authenticated client to explore,
create guarded draft proposals, and explicitly submit them. Remote `proposal_approve` and
`proposal_apply` are denied even with the bearer token. Review/approval/application remains a
trusted human/local path rather than turning possession of one network token into authority to
rewrite canonical notes.

### Docker / Compose

The repository includes a generic Linux image and Compose deployment under
`deploy/home-node/`. It is the preferred basis for a NAS, mini PC, Raspberry Pi-class server,
or another OCI-capable host.

```bash
cd /absolute/path/to/lifeos-application/deploy/home-node
cp .env.example .env
```

The generated `.env` is local deployment configuration and is ignored by the application
repository. Edit it so `LIFEOS_VAULT_PATH` points to the canonical node vault and
`LIFEOS_TOKEN_FILE` points to a token file outside that vault.

The supported image runs as fixed unprivileged UID/GID `10001:10001`. The host vault must grant
that identity read/write/execute access to the vault root and `proposals/`. Prefer a dedicated
home-node vault replica. On a dedicated Linux node where changing ownership is appropriate, one
simple preparation is:

```bash
sudo chown -R 10001:10001 /srv/lifeos/vault
```

For mounted/shared storage, use the storage provider's ownership or ACL mechanism instead of
blindly changing another device's working copy. Service startup validates this write authority
and exits with a configuration error rather than starting a read-only-looking node whose remote
proposal workflow would fail later.

Then start the node:

```bash
docker compose up -d --build
```

Compose publishes only on host loopback by default. To make the node reachable through a
private/VPN address, change **both** `LIFEOS_PUBLISH_ADDRESS` and `LIFEOS_ALLOWED_HOST` rather
than replacing the allowlist with a wildcard. Keep TLS at the reverse proxy/VPN boundary when
transport crosses an untrusted network.

The vault bind mount, including canonical Markdown and its active-node Git history, persists
across container replacement. A separate Docker volume is mounted at `/vault/.lifeos`, so
registry/index/cache/runtime state can be discarded and rebuilt without deleting canonical
vault content. The container runs as UID/GID `10001:10001`, drops Linux capabilities, uses a
read-only root filesystem, and receives the bearer token through a mounted secret file.

The full-validation gate builds and exercises this container, verifies authenticated readiness,
restart/runtime rebuild behavior, checks that non-runtime canonical/Git files remain unchanged by
service restart, and separately builds the same Dockerfile for `linux/arm64`.

### Home Assistant Yellow

A Yellow running a normal container-capable Linux host can use the same OCI/Compose path.
When the Yellow runs **Home Assistant OS**, use a thin Home Assistant App wrapper rather than
putting Supervisor-specific code into LifeOS core. Home Assistant's current App format is
container based and maps its `aarch64` architecture to Docker `linux/arm64`.

The wrapper should stay deployment-only and contain, at minimum:

- `config.yaml` declaring `arch: [aarch64]`, `startup: services`, a mapped TCP port for 8000,
  and an `image:` reference to the same versioned multi-architecture LifeOS image;
- a writable persistent `/data` area for App-owned configuration/secrets and an explicitly
  mapped Home Assistant `share`/`addon_config` location for the canonical vault when that is
  the chosen storage topology;
- a tiny startup script that maps the selected vault path, secret file, actor ID, Host
  allowlist, and port into the same `lifeos serve` command used everywhere else;
- no Supervisor/Home Assistant API, privileged mode, host networking, Docker socket, or
  embedded LLM permission unless a future task establishes a specific need.

Home Assistant documents `/data` as persistent App storage, `ports` for explicit container
port publication, `map` for allowed shared directories, and generic multi-arch `image` names
in its App configuration reference. The wrapper must also arrange write permission for the
LifeOS service identity on the mapped canonical vault. This thin wrapper is packaging around
the generic image; it is not a second LifeOS runtime or synchronization protocol.

---

[← Previous: Feature Breakdown](03-feature-breakdown.md) · [Manual home](README.md) · [Next: Workflow →](05-workflow.md)