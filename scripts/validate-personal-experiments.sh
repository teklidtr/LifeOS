#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"

python3 scripts/validate_manual_links.py
PYTHONPATH=src python3 -m pytest --import-mode=importlib \
  tests/experiments \
  tests/bridge/test_experiment_bridge.py \
  tests/e2e/test_personal_experiments.py -q

PYTHONPATH=src python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory

from lifeos.bridge.protocol import CAPABILITIES
from lifeos.experiments import EXPERIMENT_SCHEMA_VERSION, ExperimentArtifactService
from lifeos.experiments.history import rebuild_experiment_index

required = {
    "experiment.create",
    "experiment.list",
    "experiment.load",
    "experiment.design.evaluate",
    "experiment.safety.classify",
    "experiment.transition",
    "experiment.protocol.update",
    "experiment.amendment.add",
    "experiment.observation.record",
    "experiment.schedule.due",
    "experiment.analysis.run",
    "experiment.conclusion.record",
    "experiment.clone",
    "experiment.history.rebuild",
    "experiment.history.load",
    "experiment.compare",
    "experiment.proposal.preview",
    "experiment.proposal.create",
    "experiment.migration.preview",
    "experiment.migration.apply",
    "experiment.privacy.preview",
    "experiment.recovery.audit",
}
missing = sorted(required - set(CAPABILITIES))
assert not missing, f"Missing personal experiment bridge capabilities: {missing}"
assert EXPERIMENT_SCHEMA_VERSION == 1
assert Path("docs/user-manual/12-personal-experiments.md").exists()
assert not Path("tasks/ready/1508-validate-and-document-personal-experiments.md").exists(), (
    "Direction 6 release task is not completed."
)

public_paths = [
    *Path("src/lifeos/experiments").glob("*.py"),
    Path("packages/obsidian-plugin/src/experiment.ts"),
    Path("packages/obsidian-plugin/src/experiment-workspace.ts"),
]
joined = "\n".join(path.read_text(encoding="utf-8").lower() for path in public_paths)
for provider_term in ("anthropic", "claude", "openai"):
    assert provider_term not in joined, f"Provider-specific term leaked: {provider_term}"

tracked = Path(".git").exists()
if tracked:
    import subprocess
    names = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    assert "CLAUDE.md" not in names
    assert not any(name == ".claude" or name.startswith(".claude/") for name in names)

with TemporaryDirectory() as temp:
    root = Path(temp) / "vault"
    runtime = root / ".lifeos"
    root.mkdir()
    report = rebuild_experiment_index(vault_root=root, runtime_dir=runtime)
    assert report.state == "ready"
    payload = (runtime / "experiments" / "index.json").read_text(encoding="utf-8")
    assert '"schema": 1' in payload
    assert ExperimentArtifactService(vault_root=root, runtime_dir=runtime).list() == ()

print("Personal experiment release surface is compatible, provider-neutral, and rebuildable.")
PY

if python3 -m ruff --version >/dev/null 2>&1; then
  python3 -m ruff check \
    src/lifeos/experiments \
    tests/experiments \
    tests/bridge/test_experiment_bridge.py \
    tests/e2e/test_personal_experiments.py
else
  echo "UNAVAILABLE: ruff is not installed." >&2
  exit 3
fi

if python3 -m mypy --version >/dev/null 2>&1; then
  python3 -m mypy src/lifeos/experiments
else
  echo "UNAVAILABLE: mypy is not installed." >&2
  exit 3
fi

if [[ "${LIFEOS_SKIP_PLUGIN_CHECKS:-0}" != "1" ]]; then
  npm --prefix packages/obsidian-plugin run lint
  npm --prefix packages/obsidian-plugin run build
  npm --prefix packages/obsidian-plugin test
  rm -rf packages/obsidian-plugin/dist-test packages/obsidian-plugin/build
fi

git diff --check
