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

Do not place canonical vault configuration inside this runtime directory. The supported
user-facing location is `<vault>/lifeos.yml`; `.lifeos/` is disposable.

## Configuration resolution

LifeOS reads the explicit config path supplied by the caller. A vault-root `lifeos.yml` should
normally use `vault_root: .` and `runtime_dir: .lifeos`.

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
