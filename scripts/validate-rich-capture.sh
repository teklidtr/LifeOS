#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"

python_bin="python3"
if [[ -x .venv/bin/python ]]; then python_bin=".venv/bin/python"; fi

"$python_bin" scripts/validate_manual_links.py
PYTHONPATH=src "$python_bin" -m pytest --import-mode=importlib \
  tests/captures \
  tests/bridge/test_capture_bridge.py \
  tests/e2e/test_rich_capture.py -q

PYTHONPATH=src "$python_bin" - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess

from lifeos.bridge.protocol import CAPABILITIES
from lifeos.captures import ATTACHMENT_SCHEMA_VERSION, CAPTURE_SCHEMA_VERSION
from lifeos.captures.recovery import audit_capture_recovery

required = {
    "capture.create", "capture.read", "capture.update", "capture.transition",
    "capture.list", "capture.filter", "capture.visualization.build",
    "capture.attachment.add", "capture.attachment.remove", "capture.attachment.audit",
    "capture.enrichment.start", "capture.enrichment.run", "capture.enrichment.cancel",
    "capture.enrichment.retry", "capture.inference.decide", "capture.link",
    "capture.unlink", "capture.split", "capture.merge.preview", "capture.merge.apply",
    "capture.rebuild", "capture.privacy.preview", "capture.migration.preview",
    "capture.migration.apply", "capture.proposal.preview", "capture.proposal.create",
}
missing = sorted(required - set(CAPABILITIES))
assert not missing, f"Missing rich capture bridge capabilities: {missing}"
assert CAPTURE_SCHEMA_VERSION == 1
assert ATTACHMENT_SCHEMA_VERSION == 1
assert Path("docs/user-manual/13-rich-capture.md").exists()
assert not Path("tasks/ready/1608-validate-and-document-rich-capture.md").exists(), (
    "Direction 7 release task is not completed."
)

public_paths = [
    *Path("src/lifeos/captures").glob("*.py"),
    Path("packages/obsidian-plugin/src/rich-capture.ts"),
    Path("packages/obsidian-plugin/src/rich-capture-workspace.ts"),
]
joined = "\n".join(path.read_text(encoding="utf-8").casefold() for path in public_paths)
for provider_term in ("anthropic", "claude", "openai"):
    assert provider_term not in joined, f"Provider-specific term leaked into public contracts: {provider_term}"

if Path(".git").exists():
    names = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    assert "CLAUDE.md" not in names
    assert not any(name == ".claude" or name.startswith(".claude/") for name in names)

with TemporaryDirectory() as temp:
    root = Path(temp) / "vault"
    runtime = root / ".lifeos"
    root.mkdir()
    report = audit_capture_recovery(vault_root=root, runtime_dir=runtime, rebuild=True)
    assert report.index.state == "ready"

print("Rich capture release surface is provider-neutral, portable, and rebuildable.")
PY

unavailable=0
if "$python_bin" -m ruff --version >/dev/null 2>&1; then
  "$python_bin" -m ruff check \
    src/lifeos/captures \
    tests/captures \
    tests/bridge/test_capture_bridge.py \
    tests/e2e/test_rich_capture.py
else
  echo "UNAVAILABLE: ruff is not installed." >&2
  unavailable=1
fi

if "$python_bin" -m mypy --version >/dev/null 2>&1; then
  "$python_bin" -m mypy src/lifeos/captures
else
  echo "UNAVAILABLE: mypy is not installed." >&2
  unavailable=1
fi

if [[ "${LIFEOS_SKIP_PLUGIN_CHECKS:-0}" != "1" ]]; then
  npm --prefix packages/obsidian-plugin run lint
  npm --prefix packages/obsidian-plugin run typecheck
  npm --prefix packages/obsidian-plugin test
  npm --prefix packages/obsidian-plugin run build
  rm -rf packages/obsidian-plugin/dist-test packages/obsidian-plugin/build
fi

git diff --check

if [[ "$unavailable" == "1" && "${LIFEOS_ALLOW_UNAVAILABLE:-0}" != "1" ]]; then
  exit 3
fi
