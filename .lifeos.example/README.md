# Example Runtime Directory

The real `.lifeos/` directory is runtime state and should normally be ignored by Git.

> [!NOTE]
> Durable generated ownership authorization records belong at `system/generated-ownership.json`, not in `.lifeos/`.

```text
.lifeos/
  state.sqlite
  proposals/
  graphify/
  generated/
  extracted/
  logs/
  exports/
  cache/
```

Copy only configuration files you intentionally want to version.

## Configuration

Phase 1 does not search for configuration automatically. Call
`load_config(config_path)` with the exact YAML file to read. The included
`config.yml` is an example that can be adapted as `.lifeos/config.yml` inside a
vault.

Supported fields are:

| Field | Required | Default |
| --- | --- | --- |
| `vault_root` | yes | none |
| `runtime_dir` | no | `.lifeos` |
| `features.graphify` | no | `false` |
| `features.exports` | no | `false` |

`vault_root` must already exist and be a directory. `runtime_dir` may be absent;
if it exists, it must also be a directory.

A relative configuration-file path is interpreted from the current working
directory. A relative `vault_root` is then resolved from the configuration
file's directory, and a relative `runtime_dir` is resolved from the vault root.
Absolute paths are normalized but not rebased. Tildes and environment variables
are not expanded.

Unknown keys are rejected at both the top level and inside `features`. Loading
is read-only: it validates the vault and runtime paths but never creates or
modifies files or directories.
