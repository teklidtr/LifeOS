#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
python3 scripts/validate_manual_links.py
PYTHONPATH=src python3 -m pytest --import-mode=importlib \
  tests/retrieval \
  tests/conversations \
  tests/bridge/test_knowledge_conversation_bridge.py \
  tests/e2e/test_semantic_retrieval_conversations.py -q
PYTHONPATH=src python3 - <<'PY'
from pathlib import Path

from lifeos.bridge.protocol import CAPABILITIES
from lifeos.conversations import CONVERSATION_SCHEMA_VERSION
from lifeos.retrieval import INDEX_SCHEMA_VERSION

required = {
    "retrieval.index.health",
    "retrieval.index.rebuild",
    "retrieval.index.recovery.plan",
    "retrieval.index.recover",
    "retrieval.index.sync",
    "retrieval.search",
    "conversation.create",
    "conversation.list",
    "conversation.load",
    "conversation.ask",
    "conversation.scope.update",
    "conversation.source.pin",
    "conversation.source.exclude",
    "conversation.branch",
    "conversation.rename",
    "conversation.archive",
    "conversation.stale.check",
    "conversation.proposal.preview",
    "conversation.proposal.create",
}
missing = sorted(required - set(CAPABILITIES))
assert not missing, f"Missing retrieval/conversation bridge capabilities: {missing}"
assert INDEX_SCHEMA_VERSION == 1
assert CONVERSATION_SCHEMA_VERSION == 1
paths = [
    Path("src/lifeos/retrieval/contracts.py"),
    Path("src/lifeos/retrieval/index.py"),
    Path("src/lifeos/retrieval/search.py"),
    Path("src/lifeos/conversations/contracts.py"),
    Path("src/lifeos/conversations/grounding.py"),
    Path("packages/obsidian-plugin/src/knowledge-conversation.ts"),
    Path("packages/obsidian-plugin/src/knowledge-conversation-workspace.ts"),
]
joined = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
assert "anthropic" not in joined and "claude" not in joined
assert Path("docs/user-manual/11-semantic-retrieval-and-knowledge-conversations.md").exists()
assert not Path("tasks/ready/1411-validate-document-semantic-retrieval-conversations.md").exists(), (
    "Release task is not completed."
)
print("Semantic retrieval and conversation release surface is compatible and provider-neutral.")
PY
if [[ "${LIFEOS_SKIP_PLUGIN_CHECKS:-0}" != "1" ]]; then
  npm --prefix packages/obsidian-plugin run lint
  python3 - <<'PY_PLUGIN'
import json
from pathlib import Path
scripts = json.loads(Path("packages/obsidian-plugin/package.json").read_text())["scripts"]
assert scripts["lint"] == scripts["typecheck"], "Plugin lint and typecheck scripts diverged."
print("Plugin lint command also satisfies the identical typecheck gate.")
PY_PLUGIN
  npm --prefix packages/obsidian-plugin run build
  (cd packages/obsidian-plugin && node --test --test-concurrency=1 --test-force-exit dist-test/test/*.test.js)
  rm -rf packages/obsidian-plugin/dist-test
fi
git diff --check
